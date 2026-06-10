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
