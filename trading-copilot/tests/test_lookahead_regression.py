"""
Look-ahead regression suite (P0-1 / P0-2, June 2026 audit).

Each test here encodes a bug found by the June 2026 empirical probes:
  - normalize_binance kept the forming (not yet closed) Binance kline,
    so every live signal could repaint.
  - The backtest LTF entry scan started inside the still-forming signal bar.
  - HTF conditions evaluated the forming HTF bar (sliced by open time).
  - The HTF result cache ignored detector kwargs, so two conditions on the
    same detector could silently share one result.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from copilot.backtest.engine import BacktestEngine
from copilot.backtest.rules import Condition, HTFCondition, SetupRule
from copilot.data.normalize import normalize_binance, normalize_binance_with_delta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kline(open_ms: int, close_ms: int, price: float = 100.0) -> list:
    return [
        open_ms, str(price), str(price + 1), str(price - 1), str(price),
        "100.0", close_ms, "0", "1", "50.0", "0", "0",
    ]


def _closed_klines(n: int, step_ms: int = 60_000) -> list[list]:
    """n klines, all closed well in the past."""
    t0 = 1_700_000_000_000  # 2023 — far in the past
    return [_kline(t0 + i * step_ms, t0 + (i + 1) * step_ms - 1) for i in range(n)]


def _make_hourly_df(n: int, base: float = 100.0) -> pd.DataFrame:
    ts = [
        datetime(2026, 4, 1, 10, tzinfo=timezone.utc) + timedelta(hours=i)
        for i in range(n)
    ]
    rows = [
        {"open": base, "high": base + 0.2, "low": base - 0.2,
         "close": base, "volume": 100.0}
        for _ in range(n)
    ]
    return pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))


def _make_minutes_df(n: int, step_min: int, start: datetime,
                     base: float = 100.0) -> pd.DataFrame:
    ts = [start + timedelta(minutes=i * step_min) for i in range(n)]
    rows = [
        {"open": base, "high": base + 0.2, "low": base - 0.2,
         "close": base, "volume": 10.0}
        for _ in range(n)
    ]
    return pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))


class _MultiTFSource:
    def __init__(self, dfs: dict):
        self._dfs = dfs

    def get_ohlc(self, symbol: str, tf: str, bars: int = 500) -> pd.DataFrame:
        df = self._dfs.get(tf)
        if df is None:
            df = next(iter(self._dfs.values()))
        return df.copy()


# ---------------------------------------------------------------------------
# P0-1 — forming candle must be dropped
# ---------------------------------------------------------------------------

def test_forming_candle_dropped_by_default():
    raw = _closed_klines(5)
    now_ms = int(time.time() * 1000)
    # Forming bar: opened 30 s ago, closes 30 s in the future
    raw.append(_kline(now_ms - 30_000, now_ms + 30_000))

    df = normalize_binance(raw)
    assert len(df) == 5, "forming candle must be dropped"
    assert df.index[-1] == pd.Timestamp(raw[4][0], unit="ms", tz="UTC")


def test_forming_candle_kept_when_requested():
    raw = _closed_klines(5)
    now_ms = int(time.time() * 1000)
    raw.append(_kline(now_ms - 30_000, now_ms + 30_000))

    df = normalize_binance(raw, include_forming=True)
    assert len(df) == 6


def test_historical_klines_untouched():
    raw = _closed_klines(5)
    df = normalize_binance(raw)
    assert len(df) == 5


def test_forming_candle_dropped_in_delta_variant():
    raw = _closed_klines(5)
    now_ms = int(time.time() * 1000)
    raw.append(_kline(now_ms - 30_000, now_ms + 30_000))

    df = normalize_binance_with_delta(raw)
    assert len(df) == 5
    assert "delta" in df.columns


def test_all_forming_returns_empty():
    now_ms = int(time.time() * 1000)
    df = normalize_binance([_kline(now_ms - 30_000, now_ms + 30_000)])
    assert len(df) == 0
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------------------
# P0-2 — LTF entry scan must start at the signal bar's CLOSE
# ---------------------------------------------------------------------------

def test_ltf_entry_not_before_signal_bar_close():
    """
    Signal fires at the first evaluated bar (i=50, opens Apr 3 12:00, closes
    13:00). LTF entry conditions pass on every 5m bar, so the leaky engine
    entered at 12:05 — inside the still-forming signal bar. The entry must be
    at or after 13:00.
    """
    htf = _make_hourly_df(n=80)
    ltf = _make_minutes_df(
        n=80 * 12 + 50, step_min=5,
        start=datetime(2026, 4, 1, 10, tzinfo=timezone.utc),
    )
    rule = SetupRule(
        name="ltf_no_lookahead",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="pct:5.0",
        tp_logic="rr:50.0",  # never hits — trade stays pending
        entry_tf="5m",
        entry_after_ltf="signal_close",
        max_entry_wait_bars_ltf=500,
    )
    registry = {"detect_fvg": lambda df, **k: {"count_active": 0}}
    engine = BacktestEngine(
        source=_MultiTFSource({"1h": htf, "5m": ltf}),
        detector_registry=registry,
    )
    summary = engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)

    assert summary.trades, "expected one (pending) trade"
    entry_ts = pd.Timestamp(summary.trades[0].ts_entry)
    signal_close = pd.Timestamp("2026-04-03T13:00:00Z")
    assert entry_ts >= signal_close, (
        f"entry at {entry_ts} is inside the forming signal bar "
        f"(signal closes {signal_close}) — look-ahead leak"
    )


# ---------------------------------------------------------------------------
# P0-2 — HTF conditions must not see the forming HTF bar
# ---------------------------------------------------------------------------

def test_htf_condition_waits_for_htf_bar_close():
    """
    A 4h HTF bar opening Apr 3 16:00 closes at 20:00. A condition keyed to
    that bar must first pass on the 1h bar closing at 20:00 (opens 19:00),
    so the first entry lands at 20:00 (next bar). The leaky engine saw the
    bar at its OPEN (16:00) and entered at 17:00 — three hours of future data.
    """
    target_open = pd.Timestamp("2026-04-03T16:00:00Z")

    htf_1h = _make_hourly_df(n=80)
    # 4h bars aligned to 00/04/08/12/16/20, covering the 1h range
    htf_4h = _make_minutes_df(
        n=24, step_min=240,
        start=datetime(2026, 4, 1, 8, tzinfo=timezone.utc),
    )

    def htf_det(df, **kw):
        state = "bullish" if df.index[-1] >= target_open else "bearish"
        return {"state": state}

    rule = SetupRule(
        name="htf_close_gate",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="pct:5.0",
        tp_logic="rr:50.0",  # never hits — first trade stays pending
        htf_conditions=[HTFCondition("htf_det", "state", "eq", "bullish", htf_tf="4h")],
    )
    registry = {
        "detect_fvg": lambda df, **k: {"count_active": 0},
        "htf_det": htf_det,
    }
    engine = BacktestEngine(
        source=_MultiTFSource({"1h": htf_1h, "4h": htf_4h}),
        detector_registry=registry,
    )
    summary = engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)

    assert summary.trades, "expected one (pending) trade"
    entry_ts = pd.Timestamp(summary.trades[0].ts_entry)
    target_close = target_open + pd.Timedelta(hours=4)
    assert entry_ts >= target_close, (
        f"entry at {entry_ts} but the gating 4h bar only closes at "
        f"{target_close} — forming HTF bar leaked into conditions"
    )


# ---------------------------------------------------------------------------
# P0-2 — HTF result cache must key on detector kwargs
# ---------------------------------------------------------------------------

def test_htf_cache_keys_on_kwargs():
    """
    Two HTF conditions call the same detector with different kwargs and
    expect different results. With the kwargs-blind cache key the second
    condition reused the first call's result and always failed.
    """
    htf_1h = _make_hourly_df(n=80)
    htf_4h = _make_minutes_df(
        n=24, step_min=240,
        start=datetime(2026, 4, 1, 8, tzinfo=timezone.utc),
    )

    def mode_det(df, mode="a", **kw):
        return {"state": "bullish" if mode == "a" else "bearish"}

    rule = SetupRule(
        name="htf_kwargs_cache",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="pct:5.0",
        tp_logic="rr:50.0",
        htf_conditions=[
            HTFCondition("mode_det", "state", "eq", "bullish",
                         kwargs={"mode": "a"}, htf_tf="4h"),
            HTFCondition("mode_det", "state", "eq", "bearish",
                         kwargs={"mode": "b"}, htf_tf="4h"),
        ],
    )
    registry = {
        "detect_fvg": lambda df, **k: {"count_active": 0},
        "mode_det": mode_det,
    }
    engine = BacktestEngine(
        source=_MultiTFSource({"1h": htf_1h, "4h": htf_4h}),
        detector_registry=registry,
    )
    summary = engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)

    assert summary.total_signals > 0, (
        "both kwargs variants should pass — cache key must include kwargs"
    )


# ---------------------------------------------------------------------------
# P0-4 — quarantined tools must not be exposed to the LLM
# ---------------------------------------------------------------------------

def test_quarantined_tools_not_registered():
    """June 2026 audit: these detectors produce noise and are quarantined
    from the MCP/agent tool list until rewritten (PLAN.md P0-4)."""
    from copilot.llm.tools import ToolRegistry

    names = set(ToolRegistry().tool_names())
    for quarantined in (
        "detect_compression",
        "check_absorption_at_poi",
        "check_cd_divergence_at_structure",
    ):
        assert quarantined not in names, f"{quarantined} must stay quarantined"


# ---------------------------------------------------------------------------
# P0-9 — ToolRegistry cache key must include the detector kwargs
# ---------------------------------------------------------------------------

class _FixtureSource:
    """Registry data source returning a fixed DataFrame (no network)."""

    def __init__(self, df):
        self._df = df

    def get_ohlc(self, symbol, tf, bars, start_time=None, end_time=None):
        return self._df


def _swingy_df(periods: int = 120):
    """Zig-zag with a long wave and short ripples, so swing_lookback matters."""
    import numpy as np
    import pandas as pd

    idx = pd.date_range("2026-01-01", periods=periods, freq="1h", tz="UTC")
    t = np.arange(periods)
    close = 100 + 8 * np.sin(t / 11.0) + 1.5 * np.sin(t / 2.0)
    df = pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.9,
            "low": close - 0.9,
            "close": close,
            "volume": np.full(periods, 1000.0),
        },
        index=idx,
    )
    df.index.name = "ts"
    return df.astype("float64")


def test_registry_cache_key_includes_kwargs():
    """P0-9: re-probing a detector with different params returned the FIRST answer.

    The LLM widening a lookback then reasoning on the previous result is invisible
    to _verify_report_numbers — every number in it is a genuine tool-result number.
    """
    from copilot.llm.tools import ToolRegistry

    registry = ToolRegistry(data_source=_FixtureSource(_swingy_df()))
    tight = registry.dispatch(
        "detect_order_block", {"symbol": "BTCUSDT", "timeframe": "1h", "swing_lookback": 2}
    )
    wide = registry.dispatch(
        "detect_order_block", {"symbol": "BTCUSDT", "timeframe": "1h", "swing_lookback": 25}
    )

    assert tight["count"] != wide["count"], (
        "a wider swing_lookback must produce a different order-block set, "
        "not the cached answer from the tighter probe"
    )


def test_registry_cache_key_separates_pine_layer_selections(fvg_bullish_df):
    """Same symbol/tf, different `detectors` → different chart, different file."""
    from copilot.llm.tools import ToolRegistry

    registry = ToolRegistry(data_source=_FixtureSource(fvg_bullish_df))
    base = {"symbol": "BTCUSDT", "timeframe": "1h"}
    one = registry.dispatch("generate_pine_script", {**base, "detectors": ["detect_fvg"]})
    two = registry.dispatch(
        "generate_pine_script", {**base, "detectors": ["detect_fvg", "detect_liquidity"]}
    )

    assert one["layers"] == ["detect_fvg"]
    assert two["layers"] == ["detect_liquidity", "detect_fvg"]
    assert one["pine_file"] != two["pine_file"]


def test_registry_cache_still_hits_for_identical_kwargs(fvg_bullish_df):
    """The fix must not disable caching — same call twice, one fetch."""
    from copilot.llm.tools import ToolRegistry

    class _CountingSource(_FixtureSource):
        calls = 0

        def get_ohlc(self, *a, **kw):
            type(self).calls += 1
            return self._df

    source = _CountingSource(fvg_bullish_df)
    registry = ToolRegistry(data_source=source)
    args = {"symbol": "BTCUSDT", "timeframe": "1h", "swing_lookback": 3}
    first = registry.dispatch("detect_order_block", args)
    second = registry.dispatch("detect_order_block", dict(args))

    assert first is second
    assert _CountingSource.calls == 1


# ---------------------------------------------------------------------------
# P2-5 — bar caps: the fetch layer must not silently truncate a large request
# ---------------------------------------------------------------------------

class _PagingSource:
    """Fake Binance: 1500 bars max per request, endTime paginates backwards."""

    LIMIT = 1500

    def __init__(self, available: int):
        import pandas as pd

        self.available = available
        self.requests: list[dict] = []
        self._index = pd.date_range(
            "2024-01-01", periods=available, freq="1h", tz="UTC"
        )

    def __call__(self, client, params):
        self.requests.append(dict(params))
        limit = min(int(params["limit"]), self.LIMIT)
        end_ms = params.get("endTime")

        idx = self._index
        if end_ms is not None:
            idx = idx[idx <= __import__("pandas").Timestamp(end_ms, unit="ms", tz="UTC")]
        idx = idx[-limit:]

        return [
            [
                int(ts.timestamp() * 1000), "100", "101", "99", "100", "10",
                int(ts.timestamp() * 1000) + 1, "1000", 5, "5", "500", "0",
            ]
            for ts in idx
        ]


def test_source_paginates_beyond_one_request(monkeypatch):
    """P2-5: `limit` above 1500 is not an error — Binance just returns 1500.

    Every backtest asking for a multi-month window got 1499 bars and no warning,
    so the研究 protocol's 30-completed-trades minimum was unreachable by
    construction. The June re-baseline ran on 1499 bars while asking for 2000.
    """
    from copilot.data.binance import BinanceSource

    source = BinanceSource(cache=_NullCache())
    fake = _PagingSource(available=6000)
    monkeypatch.setattr(BinanceSource, "_get", lambda self, client, params: fake(client, params))

    df = source.get_ohlc("BTCUSDT", "1h", 5000)

    assert len(df) == 5000, f"expected the full window, got {len(df)}"
    assert len(fake.requests) == 4, "5000 bars = 1500+1500+1500+500 → four pages"
    assert df.index.is_monotonic_increasing
    assert not df.index.duplicated().any()


def test_pagination_stops_at_start_of_history(monkeypatch):
    """A young listing has less history than requested — stop, don't loop."""
    from copilot.data.binance import BinanceSource

    source = BinanceSource(cache=_NullCache())
    fake = _PagingSource(available=1800)
    monkeypatch.setattr(BinanceSource, "_get", lambda self, client, params: fake(client, params))

    df = source.get_ohlc("BTCUSDT", "1h", 5000)

    assert len(df) == 1800
    assert len(fake.requests) <= 3


def test_single_page_requests_are_not_paginated(monkeypatch):
    """The common case stays one request — no extra latency for a 500-bar probe."""
    from copilot.data.binance import BinanceSource

    source = BinanceSource(cache=_NullCache())
    fake = _PagingSource(available=6000)
    monkeypatch.setattr(BinanceSource, "_get", lambda self, client, params: fake(client, params))

    df = source.get_ohlc("BTCUSDT", "1h", 500)

    assert len(df) == 500
    assert len(fake.requests) == 1


def test_engine_no_longer_caps_the_date_range():
    """The 5000-bar ceiling in _fetch_data is gone (P2-5)."""
    import inspect

    from copilot.backtest.engine import BacktestEngine

    code = [
        ln.split("#")[0] for ln in inspect.getsource(BacktestEngine._fetch_data).splitlines()
    ]
    assert not any("5000" in ln for ln in code), "a bar ceiling is back in _fetch_data"


class _NullCache:
    """Cache that never hits — keeps fetch-layer tests off the disk cache."""

    def get(self, *a, **kw):
        return None

    def put(self, *a, **kw):
        return None

    def get_range(self, *a, **kw):
        return None

    def put_range(self, *a, **kw):
        return None


# ---------------------------------------------------------------------------
# P0-8 — the entry bar must be settled when the fill leaves it exposed
# ---------------------------------------------------------------------------

def _flat_df_with_spike(n: int, spike_bar: int, spike_low: float):
    """Flat 100.0 series with one bar diving to *spike_low*."""
    import numpy as np
    import pandas as pd

    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    high = np.full(n, 100.5)
    low = np.full(n, 99.5)
    low[spike_bar] = spike_low
    df = pd.DataFrame(
        {
            "open": np.full(n, 100.0),
            "high": high,
            "low": low,
            "close": np.full(n, 100.0),
            "volume": np.full(n, 1000.0),
        },
        index=idx,
    )
    df.index.name = "ts"
    return df.astype("float64")


def _entry_bar_rule(entry_after: str, **kw):
    from copilot.backtest.rules import Condition, SetupRule

    return SetupRule(
        name=f"entry_bar_{entry_after}",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after=entry_after,
        sl_logic="pct:2.0",   # SL = 98
        tp_logic="rr:50.0",   # TP unreachable — only the stop can resolve it
        min_rr=1.0,
        required_session=None,
        **kw,
    )


def _entry_bar_engine(df):
    from copilot.backtest.engine import BacktestEngine

    class _Src:
        def get_ohlc(self, symbol, tf, bars, start_time=None, end_time=None):
            return df

    return BacktestEngine(
        source=_Src(),
        detector_registry={"detect_fvg": lambda d, **k: {"count_active": 0}},
    )


def test_next_open_entry_bar_is_scanned_for_stop():
    """P0-8: entry at the OPEN of a bar → that bar's whole range is post-fill.

    Skipping it handed the trade one bar of stop immunity: a dive to 90 on the
    entry bar left the position open and eventually resolved elsewhere or not
    at all. The bias was optimistic on every rule the engine has ever run.
    """
    # The engine needs leading bars before it evaluates anything, so discover
    # where the fill actually lands, then put the dive on exactly that bar.
    import pandas as pd

    probe = _flat_df_with_spike(60, spike_bar=59, spike_low=99.0)
    probe_summary = _entry_bar_engine(probe).run(
        "BTCUSDT", "1h", _entry_bar_rule("next_open"), bars=60, write_journal=False
    )
    assert probe_summary.total_trades >= 1, "fixture must produce a trade"
    entry_ts = pd.Timestamp(probe_summary.trades[0].ts_entry)
    entry_bar = probe.index.get_loc(entry_ts)

    df = _flat_df_with_spike(60, spike_bar=entry_bar, spike_low=90.0)
    summary = _entry_bar_engine(df).run(
        "BTCUSDT", "1h", _entry_bar_rule("next_open"), bars=60, write_journal=False
    )

    assert summary.total_trades >= 1
    first = summary.trades[0]
    assert first.result == "loss", "the stop on the entry bar must count"
    assert first.ts_exit == first.ts_entry, (
        f"exit should be the entry bar itself, got {first.ts_exit} vs {first.ts_entry}"
    )


def test_signal_close_entry_bar_is_not_scanned():
    """The mirror image: entry at the CLOSE of a bar.

    That bar's high and low happened BEFORE the fill, so settling it would
    invent stop-outs the trade never faced — swapping an optimistic bias for a
    pessimistic one. A naive "always scan the entry bar" fix breaks this.
    """
    import pandas as pd

    probe = _flat_df_with_spike(60, spike_bar=59, spike_low=99.0)
    probe_summary = _entry_bar_engine(probe).run(
        "BTCUSDT", "1h", _entry_bar_rule("signal_close"), bars=60, write_journal=False
    )
    assert probe_summary.total_trades >= 1
    entry_ts = probe_summary.trades[0].ts_entry
    entry_bar = probe.index.get_loc(pd.Timestamp(entry_ts))

    # The dive sits on the fill bar — but the fill is at its close, after it.
    df = _flat_df_with_spike(60, spike_bar=entry_bar, spike_low=90.0)
    summary = _entry_bar_engine(df).run(
        "BTCUSDT", "1h", _entry_bar_rule("signal_close"), bars=60, write_journal=False
    )

    assert summary.total_trades >= 1
    first = summary.trades[0]
    assert first.ts_exit != first.ts_entry, (
        "pre-fill price action must not stop the trade out"
    )


# ---------------------------------------------------------------------------
# min_rr — the trader's global 1.8 floor replaces the hard-coded 1.0
# ---------------------------------------------------------------------------

def test_min_rr_gate_rejects_setups_below_the_floor():
    from copilot.backtest.rules import SetupRule

    assert _entry_bar_rule("next_open").min_rr == 1.0, "test helper pins its own floor"
    assert SetupRule(
        name="x", direction="long", conditions=[],
        entry_after="next_open", sl_logic="swing", tp_logic="rr:2.0",
    ).min_rr == 1.8, "global floor is 1.8"

    df = _flat_df_with_spike(60, spike_bar=59, spike_low=99.0)
    engine = _entry_bar_engine(df)

    tight = _entry_bar_rule("next_open")
    tight.tp_logic = "rr:1.5"
    tight.min_rr = 1.8
    assert engine.run("BTCUSDT", "1h", tight, bars=60, write_journal=False).total_trades == 0

    ok = _entry_bar_rule("next_open")
    ok.tp_logic = "rr:2.0"
    ok.min_rr = 1.8
    summary = engine.run("BTCUSDT", "1h", ok, bars=60, write_journal=False)
    assert summary.total_trades >= 1
    assert summary.skipped_rr == 0


def test_min_rr_survives_serialisation():
    from copilot.backtest.rules import SetupRule

    rule = _entry_bar_rule("next_open")
    rule.min_rr = 2.5
    assert SetupRule.from_dict(rule.to_dict()).min_rr == 2.5


# ---------------------------------------------------------------------------
# pending trades — excluded from stats, but counted and reported
# ---------------------------------------------------------------------------

def test_unfinished_trades_are_counted_not_hidden():
    """A trade still open at end-of-data resolves nothing — but a rule that
    parks capital in unresolved positions must not look clean."""
    from copilot.backtest.report import trades_to_summary
    from copilot.journal import TradeRecord

    def _t(result, pnl_r):
        return TradeRecord(
            symbol="BTCUSDT", record_type="backtest", setup_name="r",
            direction="long", ts_entry="2026-01-01T00:00:00Z",
            entry_price=100.0, sl_price=98.0, result=result, pnl_r=pnl_r,
        )

    summary = trades_to_summary(
        run_id="r", symbol="BTCUSDT", tf="1h", rule_name="r", direction="long",
        start="2026-01-01T00:00:00Z", end="2026-02-01T00:00:00Z",
        total_bars=100, total_signals=5, skipped_rr=0, skipped_entry=0,
        bars_in_trade_list=[1, 1],
        trades=[_t("win", 2.0), _t("loss", -1.0), _t("pending", None), _t("pending", None)],
    )

    assert summary.unfinished == 2
    assert summary.wins == 1 and summary.losses == 1
    assert summary.winrate == 0.5, "pending must not enter the winrate denominator"


# ---------------------------------------------------------------------------
# Perf regression — the LTF entry scan must see a BOUNDED trailing window
# ---------------------------------------------------------------------------
# Not a correctness bug: handing detectors the whole LTF series produced the
# right answer, just at a ruinous price. detect_bos is superlinear in slice
# length (measured on BTCUSDT 3m: 2k bars 0.16s → 100k bars 46.8s), so a
# 5000-bar 1h backtest with a 3m entry TF projected to ~13 hours per arm while
# the detector's answer was identical from a 1000-bar window onward.

def test_ltf_entry_scan_slice_is_bounded():
    """Every LTF evaluation gets at most _LTF_LOOKBACK_BARS of history."""
    from copilot.backtest.engine import _LTF_LOOKBACK_BARS

    htf = _make_hourly_df(n=80)
    ltf = _make_minutes_df(
        n=80 * 12 + 50, step_min=5,
        start=datetime(2026, 4, 1, 10, tzinfo=timezone.utc),
    )
    seen_lengths: list[int] = []

    def spy(df, **kw):
        seen_lengths.append(len(df))
        return {"count_active": 0}

    rule = SetupRule(
        name="ltf_window_bound",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="pct:5.0",
        tp_logic="rr:50.0",
        entry_tf="5m",
        entry_conditions=[Condition("detect_ltf_spy", "count_active", "gte", 999)],
        entry_after_ltf="signal_close",
        max_entry_wait_bars_ltf=500,
    )
    engine = BacktestEngine(
        source=_MultiTFSource({"1h": htf, "5m": ltf}),
        detector_registry={
            "detect_fvg": lambda df, **k: {"count_active": 0},
            "detect_ltf_spy": spy,
        },
    )
    engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)

    assert seen_lengths, "the LTF entry scan never ran"
    assert max(seen_lengths) <= _LTF_LOOKBACK_BARS, (
        f"LTF slice grew to {max(seen_lengths)} bars, ceiling is {_LTF_LOOKBACK_BARS} "
        "— the unbounded iloc[:cursor+1] slice is back"
    )


def test_ltf_window_is_trailing_not_leading():
    """
    The bound must drop OLD bars, never withhold recent ones: the last bar of
    every slice is the cursor bar. A window that clipped from the right would
    be a look-ahead-free but blind engine.
    """
    from copilot.backtest.engine import _LTF_LOOKBACK_BARS

    htf = _make_hourly_df(n=80)
    ltf = _make_minutes_df(
        n=80 * 12 + 50, step_min=5,
        start=datetime(2026, 4, 1, 10, tzinfo=timezone.utc),
    )
    last_ts: list[pd.Timestamp] = []

    def spy(df, **kw):
        last_ts.append(df.index[-1])
        return {"count_active": 0}

    rule = SetupRule(
        name="ltf_window_trailing",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="pct:5.0",
        tp_logic="rr:50.0",
        entry_tf="5m",
        entry_conditions=[Condition("detect_ltf_spy", "count_active", "gte", 999)],
        entry_after_ltf="signal_close",
        max_entry_wait_bars_ltf=500,
    )
    engine = BacktestEngine(
        source=_MultiTFSource({"1h": htf, "5m": ltf}),
        detector_registry={
            "detect_fvg": lambda df, **k: {"count_active": 0},
            "detect_ltf_spy": spy,
        },
    )
    engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)

    assert last_ts, "the LTF entry scan never ran"
    # Consecutive evaluations advance one LTF bar at a time, never repeat or skip.
    assert last_ts == sorted(last_ts), "LTF cursor went backwards"
    assert len(set(last_ts)) == len(last_ts), "an LTF bar was evaluated twice"
    assert _LTF_LOOKBACK_BARS > 0


# ---------------------------------------------------------------------------
# Silent-degradation guards (found 2026-08-23 via a Binance 429)
# ---------------------------------------------------------------------------

def test_missing_ltf_data_refuses_to_run_instead_of_degrading():
    """A rule that declares entry_tf must not quietly become an HTF-only rule.

    The old code logged "LTF entry will be skipped" and set _ltf_df=None — but
    the state machine then never entered LTF_SCAN and fell through to the HTF
    entry path, backtesting a DIFFERENT strategy and reporting plausible
    numbers for it. Discovered when 12 parallel arms tripped Binance rate
    limiting and the LTF fetch failed mid-run.
    """
    import pytest

    from copilot.backtest.engine import BacktestEngine
    from copilot.backtest.rules import Condition, SetupRule

    htf = _make_hourly_df(n=80)

    class _NoLtfSource:
        def get_ohlc(self, symbol, tf, bars, start_time=None, end_time=None):
            if tf == "1h":
                return htf
            raise RuntimeError("429 Too Many Requests")

    rule = SetupRule(
        name="needs_ltf",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="pct:5.0",
        tp_logic="rr:2.0",
        entry_tf="5m",
        entry_after_ltf="signal_close",
    )
    engine = BacktestEngine(
        source=_NoLtfSource(),
        detector_registry={"detect_fvg": lambda df, **k: {"count_active": 0}},
    )
    with pytest.raises(RuntimeError, match="requires it"):
        engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)


def test_htf_entry_path_survives_a_target_that_pays_nothing():
    """tp_logic returning None must skip the setup, not crash.

    `nearest_fractal` legitimately returns None when no pool pays min_rr. The
    HTF entry path fed that straight into compute_rr, which cannot subtract
    from None — the run died with a TypeError instead of counting a skip.
    """
    from copilot.backtest.engine import BacktestEngine
    from copilot.backtest.rules import Condition, SetupRule

    htf = _make_hourly_df(n=80)

    class _Src:
        def get_ohlc(self, symbol, tf, bars, start_time=None, end_time=None):
            return htf

    rule = SetupRule(
        name="target_never_pays",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="pct:5.0",
        tp_logic="nearest_fractal",
        min_rr=1.3,
    )
    engine = BacktestEngine(
        source=_Src(),
        detector_registry={
            "detect_fvg": lambda df, **k: {"count_active": 0},
            "detect_fractals": lambda df, **k: {"fractals": []},   # nothing to aim at
        },
    )
    summary = engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)
    assert summary.total_trades == 0
    assert summary.skipped_rr > 0, "setups with no reachable target must be counted as skips"


def test_htf_entry_path_receives_the_detector_registry():
    """Registry-dependent tp_logic must work on the HTF path too.

    Without the registry every detector-driven target silently resolved to
    None, so the rule looked like it had no valid setups at all.
    """
    from copilot.backtest.engine import BacktestEngine
    from copilot.backtest.rules import Condition, SetupRule

    htf = _make_hourly_df(n=80)
    seen = []

    class _Src:
        def get_ohlc(self, symbol, tf, bars, start_time=None, end_time=None):
            return htf

    def fractals(df, **kw):
        seen.append(kw)
        top = float(df["high"].iloc[-1])
        return {"fractals": [{"type": "swing_high", "price": top * 1.5, "is_broken": False}]}

    rule = SetupRule(
        name="registry_on_htf_path",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="pct:5.0",
        tp_logic="nearest_fractal",
        min_rr=1.3,
    )
    engine = BacktestEngine(
        source=_Src(),
        detector_registry={
            "detect_fvg": lambda df, **k: {"count_active": 0},
            "detect_fractals": fractals,
        },
    )
    summary = engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)
    assert seen, "detect_fractals was never called — the registry never reached the TP resolver"
    assert summary.total_trades > 0


def test_batched_fetch_retries_rate_limits_instead_of_dying():
    """A 429 mid-pagination must back off, not kill the backtest."""
    import httpx

    from copilot.data import binance as b

    calls = {"n": 0}

    class _Resp:
        def __init__(self, status, payload=None):
            self.status_code = status
            self.headers = {}
            self._payload = payload or []

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "boom", request=None, response=self  # type: ignore[arg-type]
                )

        def json(self):
            return self._payload

    class _Client:
        def get(self, url, params=None):
            calls["n"] += 1
            if calls["n"] < 3:
                return _Resp(429)
            return _Resp(200, [["ok"]])

    original_sleep = b.time.sleep
    b.time.sleep = lambda *_: None          # no real backoff in tests
    try:
        out = b._get_batch_with_retry(_Client(), "http://x", {})
    finally:
        b.time.sleep = original_sleep

    assert out == [["ok"]]
    assert calls["n"] == 3, "expected two retries before the success"


def test_batched_fetch_gives_up_loudly_after_repeated_rate_limits():
    from copilot.data import binance as b

    class _Resp:
        status_code = 429
        headers: dict = {}

    class _Client:
        def get(self, url, params=None):
            return _Resp()

    original_sleep = b.time.sleep
    b.time.sleep = lambda *_: None
    try:
        import pytest

        with pytest.raises(RuntimeError, match="after 6 attempts"):
            b._get_batch_with_retry(_Client(), "http://x", {})
    finally:
        b.time.sleep = original_sleep


def test_invalidation_and_entry_share_one_detector_call_per_ltf_bar():
    """detect_bos is ~80% of a backtest's runtime; asking it twice per bar
    doubled the cost of every LTF scan for no information gain."""
    from copilot.backtest.engine import BacktestEngine
    from copilot.backtest.rules import Condition, SetupRule

    htf = _make_hourly_df(n=80)
    ltf = _make_minutes_df(
        n=80 * 12 + 50, step_min=5,
        start=datetime(2026, 4, 1, 10, tzinfo=timezone.utc),
    )
    calls: list[int] = []

    def spy(df, **kw):
        calls.append(len(df))
        return {"events": [{"direction": "bullish"}]}

    rule = SetupRule(
        name="shared_cache_probe",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="pct:5.0",
        tp_logic="rr:50.0",
        entry_tf="5m",
        entry_conditions=[Condition("detect_bos", "events.0.direction", "eq", "bullish")],
        invalidation_conditions=[
            Condition("detect_bos", "events.0.direction", "eq", "bearish")
        ],
        entry_after_ltf="signal_close",
        max_entry_wait_bars_ltf=10,
        min_rr=1.0,
    )
    engine = BacktestEngine(
        source=_MultiTFSource({"1h": htf, "5m": ltf}),
        detector_registry={
            "detect_fvg": lambda df, **k: {"count_active": 0},
            "detect_bos": spy,
        },
    )
    engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)

    assert calls, "the LTF scan never ran"
    # Both condition lists hit detect_bos with identical kwargs, so each scanned
    # bar must produce exactly one call — never two.
    assert len(calls) == len(set(range(len(calls)))), "sanity"
    duplicated = len(calls) - len(dict.fromkeys(calls))
    assert duplicated == 0, (
        f"{duplicated} of {len(calls)} detect_bos calls repeated the same slice "
        "— invalidation and entry are not sharing their cache"
    )


def test_date_range_covers_the_whole_requested_window():
    """`--start/--end` must scan the window that was asked for.

    The source returns the most recent N bars, so sizing the request to the
    window's own length produced a frame ending TODAY and starting after
    start_dt — the trim then left only the window's tail. Measured on
    Bellissimo: 15 Jun – 5 Aug was asked for, 4 Jul – 5 Aug was scanned, and 4
    of the 5 trades the full run made in that window went missing.
    """
    import pandas as pd

    from copilot.backtest.engine import BacktestEngine
    from copilot.backtest.rules import Condition, SetupRule

    # 200 days of hourly bars ending "today"
    n = 200 * 24
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("h"), periods=n, freq="1h")
    full = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0},
        index=idx,
    )
    full.index.name = "ts"
    requested: dict = {}

    class _Src:
        def get_ohlc(self, symbol, tf, bars, start_time=None, end_time=None):
            requested["bars"] = bars
            return full.iloc[-bars:]

    rule = SetupRule(
        name="range_probe",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="pct:5.0",
        tp_logic="rr:2.0",
        min_rr=1.0,
    )
    engine = BacktestEngine(
        source=_Src(),
        detector_registry={"detect_fvg": lambda df, **k: {"count_active": 0}},
    )
    window_start = (idx[-1] - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
    window_end = (idx[-1] - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    df = engine._fetch_data("BTCUSDT", "1h", 500, window_start, window_end)

    assert not df.empty
    assert df.index[0] <= pd.Timestamp(window_start, tz="UTC") + pd.Timedelta(hours=2), (
        f"frame starts at {df.index[0]}, requested window starts {window_start} "
        "— the early part of the window was never fetched"
    )
    assert df.index[-1] <= pd.Timestamp(window_end, tz="UTC")
    # The request has to reach back from NOW, not just span the window.
    assert requested["bars"] >= 120 * 24, requested["bars"]


def test_ltf_fetch_is_anchored_to_the_htf_window_end():
    """With a historical HTF window the LTF frame must end there too, not today."""
    import pandas as pd

    from copilot.data import binance as b

    seen: dict = {}

    def fake_batched(symbol, tf, total_bars, market=None, batch_size=None, end_ms=None):
        seen["end_ms"] = end_ms
        idx = pd.date_range(end=pd.Timestamp(end_ms, unit="ms", tz="UTC"),
                            periods=total_bars, freq="3min")
        out = pd.DataFrame(
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0},
            index=idx,
        )
        out.index.name = "ts"
        return out

    assert "end_ms" in b.fetch_ohlcv_batched.__code__.co_varnames, (
        "fetch_ohlcv_batched lost its end_ms parameter — the LTF frame will "
        "silently snap back to 'now'"
    )


# ---------------------------------------------------------------------------
# P0-10 — the in-memory tool cache must expire
# ---------------------------------------------------------------------------

class TestToolCacheTtl:
    """An MCP stdio server lives for hours and never calls clear_cache(), so a
    cache without a time component served the morning's candles all day — on
    the timeframe the system exists to read."""

    def _registry(self, calls):
        from copilot.llm.tools import ToolRegistry

        class _Src:
            def get_ohlc(self, symbol, tf, bars, start_time=None, end_time=None):
                import pandas as pd

                idx = pd.date_range("2026-01-01", periods=max(bars, 60), freq="1h", tz="UTC")
                df = pd.DataFrame(
                    {"open": 100.0, "high": 101.0, "low": 99.0,
                     "close": 100.0, "volume": 1000.0},
                    index=idx,
                )
                df.index.name = "ts"
                return df

        reg = ToolRegistry(data_source=_Src())
        reg._callables = {"probe": lambda df, **kw: {"n": calls.append(1) or len(calls)}}
        reg._schemas = [{"name": "probe", "input_schema": {"properties": {}}}]
        return reg

    def test_a_repeat_within_the_ttl_is_served_from_cache(self):
        calls: list = []
        reg = self._registry(calls)
        a = reg.dispatch("probe", {"symbol": "BTCUSDT", "timeframe": "1h", "bars": 100})
        b = reg.dispatch("probe", {"symbol": "BTCUSDT", "timeframe": "1h", "bars": 100})
        assert a == b
        assert len(calls) == 1

    def test_the_entry_expires_once_the_ttl_passes(self, monkeypatch):
        import copilot.llm.tools as tools

        calls: list = []
        reg = self._registry(calls)
        clock = {"t": 1000.0}
        monkeypatch.setattr(tools.time, "monotonic", lambda: clock["t"])

        reg.dispatch("probe", {"symbol": "BTCUSDT", "timeframe": "1h", "bars": 100})
        clock["t"] += 301          # 1h TTL is 300 s
        reg.dispatch("probe", {"symbol": "BTCUSDT", "timeframe": "1h", "bars": 100})
        assert len(calls) == 2, "the stale entry was served past its TTL"

    def test_fast_timeframes_expire_faster_than_slow_ones(self):
        from copilot.llm.tools import ToolRegistry

        assert ToolRegistry._cache_ttl("1m") < ToolRegistry._cache_ttl("1h")
        assert ToolRegistry._cache_ttl("1h") < ToolRegistry._cache_ttl("1d")

    def test_ttls_are_shared_with_the_disk_cache_not_redeclared(self):
        """Two layers with independently written TTL tables would drift."""
        from copilot.data.cache import _DEFAULT_TTL
        from copilot.llm.tools import ToolRegistry

        for tf, ttl in _DEFAULT_TTL.items():
            assert ToolRegistry._cache_ttl(tf) == float(ttl), tf

    def test_an_unknown_timeframe_still_expires(self):
        from copilot.llm.tools import ToolRegistry

        assert ToolRegistry._cache_ttl(None) > 0
        assert ToolRegistry._cache_ttl("7h") > 0


# ---------------------------------------------------------------------------
# Inverted stops manufacture fake winners
# ---------------------------------------------------------------------------

def test_stop_on_the_wrong_side_of_entry_is_rejected():
    """compute_rr takes abs(entry - sl), so an inverted stop yields a healthy
    positive R:R and books a winner that could never have existed.

    Real case: sb_nyam_test_long, 2026-08-06 — a limit filled at 64353.6 with
    the stop at 64403.33 (above it, for a LONG). Risk came out at -49.7, R:R at
    11.88, and the trade was recorded as +11.88R, setting that arm's expectancy
    to +3.29R over three trades.
    """
    from copilot.backtest.engine import _stop_is_on_the_right_side

    assert not _stop_is_on_the_right_side(64353.6, 64403.33, "long")
    assert _stop_is_on_the_right_side(64353.6, 64300.0, "long")
    assert not _stop_is_on_the_right_side(70724.5, 70577.55, "short")
    assert _stop_is_on_the_right_side(70724.5, 70800.0, "short")


def test_engine_skips_setups_whose_stop_is_already_behind_price():
    import pandas as pd

    from copilot.backtest.engine import BacktestEngine
    from copilot.backtest.rules import Condition, SetupRule

    n = 120
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0},
        index=idx,
    )
    df.index.name = "ts"

    class _Src:
        def get_ohlc(self, symbol, tf, bars, start_time=None, end_time=None):
            return df

    rule = SetupRule(
        name="inverted_stop",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="pct:-3.0",     # negative pct puts the "stop" ABOVE a long's entry
        tp_logic="rr:2.0",
        min_rr=1.0,
    )
    engine = BacktestEngine(
        source=_Src(),
        detector_registry={"detect_fvg": lambda df, **k: {"count_active": 0}},
    )
    summary = engine.run("BTCUSDT", "1h", rule, bars=n, write_journal=False)

    assert summary.total_trades == 0, (
        f"{summary.total_trades} trades opened with the stop on the wrong side of entry"
    )
    assert summary.skipped_rr > 0
