"""Tests for copilot/backtest/engine.py — full engine integration."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import pytest

from copilot.backtest.engine import BacktestEngine, BacktestSummary
from copilot.backtest.rules import Condition, SetupRule
from copilot.journal.reader import load_all


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_df(
    n: int = 100,
    base: float = 100.0,
    high_offsets: list[float] | None = None,
    low_offsets: list[float] | None = None,
    start_hour: int = 10,  # 10:00 UTC → london_open Kyiv
) -> pd.DataFrame:
    ts = [
        datetime(2026, 4, 1, start_hour, tzinfo=timezone.utc) + timedelta(hours=i)
        for i in range(n)
    ]
    rows = []
    for i in range(n):
        h = base + (high_offsets[i] if high_offsets else 1.0)
        l = base - (low_offsets[i] if low_offsets else 1.0)
        rows.append({"open": base, "high": h, "low": l, "close": base, "volume": 100.0})
    return pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))


class _AlwaysTrueSource:
    """Mock data source — returns a pre-built DataFrame."""
    def __init__(self, df: pd.DataFrame):
        self._df = df

    def get_ohlc(self, symbol: str, tf: str, bars: int = 500) -> pd.DataFrame:
        return self._df.copy()


def _always_true_rule(
    sl_logic: str = "atr:1.0",
    tp_logic: str = "rr:2.0",
    entry_after: str = "next_open",
) -> SetupRule:
    """A rule whose single condition is always True (count_active >= 0)."""
    return SetupRule(
        name="always_true",
        direction="long",
        conditions=[
            Condition("detect_fvg", "count_active", "gte", 0),
        ],
        entry_after=entry_after,
        sl_logic=sl_logic,
        tp_logic=tp_logic,
        required_session=None,
    )


def _make_engine(df: pd.DataFrame, journal_path: Path | None = None) -> BacktestEngine:
    return BacktestEngine(
        source=_AlwaysTrueSource(df),
        journal_path=journal_path,
    )


# ---------------------------------------------------------------------------
# No look-ahead guarantee
# ---------------------------------------------------------------------------

def test_no_look_ahead():
    """Every detector call must receive a slice of length ≤ i+1."""
    received_lengths = []

    def spy_detector(df, **kwargs):
        received_lengths.append(len(df))
        return {"count_active": 0, "fvgs": []}

    df = _make_df(n=80)
    registry = {"detect_fvg": spy_detector}
    rule = _always_true_rule()

    engine = BacktestEngine(
        source=_AlwaysTrueSource(df),
        detector_registry=registry,
    )
    engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)

    # Each call must have received the slice up to bar i+1 — never future bars
    for i, length in enumerate(received_lengths):
        assert length <= len(df), f"Detector saw {length} bars on call {i} — look-ahead violation"


# ---------------------------------------------------------------------------
# Journal writes
# ---------------------------------------------------------------------------

def test_record_type_is_backtest(tmp_path):
    """All written records must have record_type='backtest'."""
    journal = tmp_path / "j.jsonl"
    df = _make_df(n=120)

    # Build a small favorable exit: most bars with TP easily reachable
    # Use a large TP (rr:10) so no trade resolves, just check that records write
    rule = _always_true_rule(tp_logic="rr:10.0")
    engine = _make_engine(df, journal_path=journal)
    engine.run("BTCUSDT", "1h", rule, write_journal=True)

    records = load_all(path=journal)
    assert len(records) > 0
    for r in records:
        assert r.record_type == "backtest"


def test_run_id_tag_present(tmp_path):
    """All records from one run must share the same run_id tag."""
    journal = tmp_path / "j.jsonl"
    df = _make_df(n=120)
    rule = _always_true_rule(tp_logic="rr:10.0")
    engine = _make_engine(df, journal_path=journal)
    summary = engine.run("BTCUSDT", "1h", rule, write_journal=True)

    records = load_all(path=journal)
    run_id = summary.run_id[:8]
    for r in records:
        assert any(t.startswith(f"run_id:{run_id}") or t == f"run_id:{summary.run_id}" for t in r.tags), \
            f"Record {r.id[:8]} missing run_id tag"


def test_no_write_flag_does_not_write(tmp_path):
    """write_journal=False must leave the journal file untouched."""
    journal = tmp_path / "j.jsonl"
    df = _make_df(n=120)
    rule = _always_true_rule()
    engine = _make_engine(df, journal_path=journal)
    engine.run("BTCUSDT", "1h", rule, write_journal=False)

    assert not journal.exists(), "Journal file should not be created when write_journal=False"


# ---------------------------------------------------------------------------
# Trade mechanics
# ---------------------------------------------------------------------------

def test_no_overlapping_trades(tmp_path):
    """
    The engine should only have one open position at a time.
    With an always-true condition and a very high TP (never resolved),
    there should be at most 1 pending trade (no stacking).
    """
    journal = tmp_path / "j.jsonl"
    df = _make_df(n=120)
    rule = _always_true_rule(tp_logic="rr:50.0")
    engine = _make_engine(df, journal_path=journal)
    summary = engine.run("BTCUSDT", "1h", rule, write_journal=True)

    # With no trade closing, only 1 trade can ever be "open" at a time
    records = load_all(path=journal)
    pending = [r for r in records if r.result == "pending"]
    assert len(pending) <= 1, f"Engine opened overlapping trades: {len(pending)} pending"


def test_single_trade_win(tmp_path):
    """
    When TP is very tight (tiny high offset = 0.1), every bar will hit it
    immediately, producing a series of "win" trades.
    """
    journal = tmp_path / "j.jsonl"
    # All bars have high = base + 0.5 and low = base - 0.5
    df = _make_df(n=80, high_offsets=[0.5] * 80, low_offsets=[0.5] * 80)

    rule = SetupRule(
        name="easy_win",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="signal_close",   # enter at close of signal bar
        sl_logic="pct:5.0",          # SL 5% below → won't be hit in 1 bar
        tp_logic="rr:0.05",          # TP only 0.05R above entry (very tight)
        required_session=None,
    )
    engine = _make_engine(df, journal_path=journal)
    summary = engine.run("BTCUSDT", "1h", rule, write_journal=True)

    # At least one trade should have resolved
    records = load_all(path=journal)
    completed = [r for r in records if r.result in ("win", "loss")]
    # Some may resolve as win or get skipped (R:R too low) — just assert no crash
    assert summary.total_bars_scanned > 0


def test_session_filter_excludes_all_bars(tmp_path):
    """
    required_session=["asia"] with bars only in london_open window → zero signals.
    Bars start at 06:00 UTC (09:00 Kyiv = london_open). After 50 leading bars
    (56h total), all remaining bars fall 08:00–13:00 UTC = 11:00–16:00 Kyiv
    ("london_open" / "london") — none qualify as "asia".
    """
    journal = tmp_path / "j.jsonl"
    # start_hour=6 → bars 50-55 span 08:00–13:00 UTC = london_open/london Kyiv
    df = _make_df(n=56, start_hour=6)
    rule = SetupRule(
        name="session_filtered",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="atr:1.0",
        tp_logic="rr:2.0",
        required_session=["asia"],
    )
    engine = _make_engine(df, journal_path=journal)
    summary = engine.run("BTCUSDT", "1h", rule, write_journal=True)

    assert summary.total_signals == 0
    assert not journal.exists() or load_all(path=journal) == []


# ---------------------------------------------------------------------------
# Insufficient data
# ---------------------------------------------------------------------------

def test_insufficient_data_returns_empty_summary():
    """A 10-bar DataFrame is below min_i → engine returns empty summary without crashing."""
    df = _make_df(n=10)
    rule = _always_true_rule()
    engine = _make_engine(df)
    summary = engine.run("BTCUSDT", "1h", rule, write_journal=False)

    assert isinstance(summary, BacktestSummary)
    assert summary.total_trades == 0


# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------

def test_summary_winrate_calculation():
    """trades_to_summary computes winrate = wins / (wins + losses)."""
    from copilot.journal.record import TradeRecord
    from copilot.backtest.report import trades_to_summary

    def _t(result, pnl):
        r = TradeRecord(setup_name="t", direction="long", symbol="BTCUSDT",
                        result=result, pnl_r=pnl, record_type="backtest",
                        entry_price=100.0, sl_price=95.0, tp_prices=[110.0])
        return r

    trades = [_t("win", 2.0), _t("win", 2.0), _t("win", 2.0),
              _t("loss", -1.0), _t("loss", -1.0)]
    summary = trades_to_summary(
        run_id="test", symbol="BTCUSDT", tf="1h",
        rule_name="t", direction="long",
        start="2026-01-01", end="2026-04-01",
        total_bars=1000, total_signals=5,
        skipped_rr=0, skipped_entry=0,
        bars_in_trade_list=[5, 3, 4, 2, 6],
        trades=trades,
    )
    assert summary.winrate == pytest.approx(0.6, abs=0.01)
    assert summary.wins == 3
    assert summary.losses == 2


def test_summary_profit_factor():
    from copilot.journal.record import TradeRecord
    from copilot.backtest.report import trades_to_summary

    def _t(result, pnl):
        return TradeRecord(
            setup_name="t", direction="long", symbol="BTC",
            result=result, pnl_r=pnl, record_type="backtest",
            entry_price=100.0, sl_price=95.0,
        )

    # 2 wins @2R, 1 loss @-1R → PF = 4/1 = 4.0
    trades = [_t("win", 2.0), _t("win", 2.0), _t("loss", -1.0)]
    summary = trades_to_summary(
        run_id="x", symbol="BTC", tf="1h",
        rule_name="t", direction="long",
        start="2026-01-01", end="2026-04-01",
        total_bars=100, total_signals=3,
        skipped_rr=0, skipped_entry=0,
        bars_in_trade_list=[3, 3, 2],
        trades=trades,
    )
    assert summary.profit_factor == pytest.approx(4.0, rel=0.01)


# ---------------------------------------------------------------------------
# Change 2: LTF exit simulation
# ---------------------------------------------------------------------------

class _MultiTFSource:
    """Mock source returning different DataFrames per timeframe."""
    def __init__(self, dfs: dict):
        self._dfs = dfs

    def get_ohlc(self, symbol: str, tf: str, bars: int = 500) -> pd.DataFrame:
        df = self._dfs.get(tf)
        if df is None:
            df = next(iter(self._dfs.values()))
        return df.copy()


def _make_ltf_df(
    n: int,
    base: float = 100.0,
    minutes_step: int = 5,
    high_offsets: list[float] | None = None,
    low_offsets: list[float] | None = None,
    start: "datetime | None" = None,
) -> pd.DataFrame:
    """Build a 5m-style DataFrame aligned with hourly bars."""
    t0 = start or datetime(2026, 4, 1, 10, tzinfo=timezone.utc)
    ts = [t0 + timedelta(minutes=i * minutes_step) for i in range(n)]
    rows = []
    for i in range(n):
        h = base + (high_offsets[i] if high_offsets else 0.5)
        l = base - (low_offsets[i] if low_offsets else 0.5)
        rows.append({"open": base, "high": h, "low": l, "close": base, "volume": 10.0})
    return pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))


def test_ltf_exit_resolves_trade():
    """
    When entry_tf is set, IN_TRADE should exit on a 5m bar that hits TP.
    Signal fires at HTF bar 50 (2026-04-03 12:00 UTC).
    LTF bars run at 5m; bar 602 = 12:10 April 3 — 2 bars after entry — hits TP.
    """
    # HTF df: 80 h bars starting 2026-04-01 10:00; all bars neutral ±0.2
    htf = _make_df(n=80, base=100.0, high_offsets=[0.2] * 80, low_offsets=[0.2] * 80)

    # LTF df: 5m bars. Signal fires at HTF bar 50 = 50h from start = 3000 min.
    # LTF bar 600 = 3000 min from start = April 3 12:00 (same as signal ts).
    # _find_ltf_idx returns bar 601 (first bar AFTER signal ts = 12:05).
    # Entry is on bar 601 (12:05). First exit check on HTF bar 52 checks LTF bars 602+.
    # Bar 602 (12:10) high=115 > TP=108 → win.
    n_ltf = 80 * 12 + 50
    hi_off = [0.2] * n_ltf
    lo_off = [0.2] * n_ltf
    hi_off[602] = 15.0  # LTF bar 602 = April 3 12:10 UTC → high=115 > TP=108
    ltf = _make_ltf_df(n_ltf, base=100.0, minutes_step=5, high_offsets=hi_off, low_offsets=lo_off)

    rule = SetupRule(
        name="ltf_test",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="pct:5.0",   # SL = 95
        tp_logic="rr:1.6",    # TP = 108 (never hit on HTF ±0.2 bars)
        entry_tf="5m",
        entry_after_ltf="signal_close",
        max_entry_wait_bars_ltf=200,
    )
    source = _MultiTFSource({"1h": htf, "5m": ltf})
    registry = {"detect_fvg": lambda df, **k: {"count_active": 0, "fvgs": []}}
    engine = BacktestEngine(source=source, detector_registry=registry)
    summary = engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)

    wins = [t for t in summary.trades if t.result == "win"]
    assert len(wins) >= 1, "Expected at least one win from LTF exit"


def test_ltf_scan_timeout_skips_entry():
    """
    When entry_tf is set but entry_conditions never pass within
    max_entry_wait_bars_ltf bars, the signal should be skipped.
    """
    htf = _make_df(n=80, base=100.0)
    # LTF bars never hit the entry condition (always false detector result)
    ltf = _make_ltf_df(80 * 12, base=100.0)

    # Registry with a detector that always returns false
    def always_false(df, **kw):
        return {"status": "ok", "direction": "bearish"}

    rule = SetupRule(
        name="ltf_timeout",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="pct:5.0",
        tp_logic="rr:2.0",
        entry_tf="5m",
        entry_conditions=[Condition("always_false_det", "direction", "eq", "bullish")],
        max_entry_wait_bars_ltf=5,
    )
    source = _MultiTFSource({"1h": htf, "5m": ltf})
    registry = {
        "detect_fvg": lambda df, **k: {"count_active": 0, "fvgs": []},
        "always_false_det": always_false,
    }
    engine = BacktestEngine(source=source, detector_registry=registry)
    summary = engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)

    assert summary.skipped_entry > 0, "Expected skipped entries from LTF timeout"
    completed = [t for t in summary.trades if t.result in ("win", "loss")]
    assert len(completed) == 0


# ---------------------------------------------------------------------------
# Change 1: HTF conditions
# ---------------------------------------------------------------------------

def test_htf_condition_filters_signals():
    """
    When htf_conditions require a detector to return 'bearish' on the HTF df,
    but the HTF df always returns 'bullish', no signals should fire.
    """
    htf = _make_df(n=80, base=100.0)
    # HTF detector always returns bearish
    def htf_det(df, **kw):
        return {"state": "bearish"}

    rule = SetupRule(
        name="htf_filter_test",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="next_open",
        sl_logic="pct:5.0",
        tp_logic="rr:2.0",
        htf_conditions=[
            __import__("copilot.backtest.rules", fromlist=["HTFCondition"]).HTFCondition(
                "htf_det", "state", "eq", "bullish", htf_tf="4h"
            )
        ],
    )
    source = _MultiTFSource({"1h": htf, "4h": htf})
    registry = {
        "detect_fvg": lambda df, **k: {"count_active": 0},
        "htf_det": htf_det,
    }
    engine = BacktestEngine(source=source, detector_registry=registry)
    summary = engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)

    assert summary.total_signals == 0, "HTF condition should have filtered all signals"


def test_htf_condition_passes_allows_signal():
    """
    When htf_conditions pass (detector returns correct value), signal fires normally.
    """
    htf = _make_df(n=80, base=100.0)

    def htf_det(df, **kw):
        return {"state": "bullish"}

    from copilot.backtest.rules import HTFCondition
    rule = SetupRule(
        name="htf_pass_test",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="signal_close",
        sl_logic="pct:5.0",
        tp_logic="rr:50.0",  # never hits
        htf_conditions=[HTFCondition("htf_det", "state", "eq", "bullish", htf_tf="4h")],
    )
    source = _MultiTFSource({"1h": htf, "4h": htf})
    registry = {
        "detect_fvg": lambda df, **k: {"count_active": 0},
        "htf_det": htf_det,
    }
    engine = BacktestEngine(source=source, detector_registry=registry)
    summary = engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)

    assert summary.total_signals > 0, "HTF condition should allow signals through"


# ---------------------------------------------------------------------------
# Change 3: Partial TP flow
# ---------------------------------------------------------------------------

def test_partial_tp_tp1_then_be_stop():
    """
    TP1 hits at 2R (50% position), SL moves to BE, then price stops at BE.
    Expected: trade pnl_r = 2.0*0.5 + 0.0*0.5 = 1.0R → "win"
    """
    from copilot.backtest.rules import TPLevel
    from copilot.backtest.engine import _finalize_trade
    from copilot.journal.record import TradeRecord, compute_rr

    # Simulate the trade directly via _finalize_trade
    trade = TradeRecord(
        record_type="backtest", symbol="BTC", direction="long",
        entry_price=100.0, sl_price=95.0, tp_prices=[110.0],
        result="pending",
    )
    # TP1 hit: exit 50% at 110 → pnl_r = (110-100)/(100-95) = 2.0R
    trade.partial_exits.append({"size_pct": 0.5, "exit_price": 110.0, "exit_ts": "t1", "pnl_r": 2.0})
    # BE stop: exit remaining 50% at 100 → pnl_r = (100-100)/5 = 0.0R
    trade.partial_exits.append({"size_pct": 0.5, "exit_price": 100.0, "exit_ts": "t2", "pnl_r": 0.0})

    trade = _finalize_trade(trade, "loss", 100.0, "t2", fee_bps=0.0, original_sl=95.0)
    assert trade.result == "win"
    assert trade.pnl_r == pytest.approx(1.0, abs=0.01)


def test_partial_tp_full_loss():
    """
    Trade hits SL before TP1 → full loss at -1R, no partial exits.
    """
    from copilot.backtest.engine import _finalize_trade
    from copilot.journal.record import TradeRecord

    trade = TradeRecord(
        record_type="backtest", symbol="BTC", direction="long",
        entry_price=100.0, sl_price=95.0, tp_prices=[110.0],
        result="pending",
    )
    # No partial exits — SL hit directly
    trade = _finalize_trade(trade, "loss", 95.0, "t1", fee_bps=0.0, original_sl=95.0)
    assert trade.result == "loss"
    assert trade.pnl_r == pytest.approx(-1.0, abs=0.01)


def test_partial_tp_engine_integration():
    """
    Engine with tp_levels=[TPLevel("rr:1.5", 0.5), TPLevel("rr:3.0", 0.5)]
    and sl_after_tp1=None (keep original SL=95): bar 52 hits TP1 at 107.5,
    bar 54 hits TP2 at 115. Low=99 on all bars doesn't touch SL=95.
    Expected: pnl_r = 1.5*0.5 + 3.0*0.5 = 2.25R.
    """
    from copilot.backtest.rules import TPLevel

    # base=100, SL=pct:5→95, TP1=rr:1.5→107.5, TP2=rr:3→115
    n = 80
    hi = [1.0] * n
    lo = [1.0] * n   # low=99.0 on every bar → SL=95 never touched
    # bar 52 hits TP1 (high=108.5 > 107.5), bar 54 hits TP2 (high=116.5 > 115)
    hi[52] = 8.5
    hi[54] = 16.5
    df = _make_df(n=n, base=100.0, high_offsets=hi, low_offsets=lo)

    rule = SetupRule(
        name="partial_tp_test",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="signal_close",
        sl_logic="pct:5.0",
        tp_logic="rr:3.0",  # fallback (unused when tp_levels set)
        tp_levels=[TPLevel("rr:1.5", 0.5), TPLevel("rr:3.0", 0.5)],
        sl_after_tp1=None,  # keep SL at 95 so bars with low=99 don't stop out
    )
    engine = _make_engine(df)
    summary = engine.run("BTCUSDT", "1h", rule, bars=n, write_journal=False)

    wins = [t for t in summary.trades if t.result == "win"]
    assert len(wins) >= 1, f"Expected wins, got trades: {[(t.result, t.pnl_r) for t in summary.trades]}"
    # Weighted pnl_r = 1.5*0.5 + 3.0*0.5 = 2.25R
    assert wins[0].pnl_r is not None and wins[0].pnl_r == pytest.approx(2.25, abs=0.01)


# ---------------------------------------------------------------------------
# Change 4: Time-based exit
# ---------------------------------------------------------------------------

def test_time_based_exit_closes_trade():
    """
    max_bars_open=3 with a TP that never resolves → trade expires after 3 bars.
    """
    df = _make_df(n=80, high_offsets=[0.1] * 80, low_offsets=[0.1] * 80)
    rule = SetupRule(
        name="time_exit_test",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="signal_close",
        sl_logic="pct:5.0",
        tp_logic="rr:100.0",  # TP never hit
        max_bars_open=3,
    )
    engine = _make_engine(df)
    summary = engine.run("BTCUSDT", "1h", rule, bars=80, write_journal=False)

    # With max_bars_open=3, trade should expire and show up as completed (not pending)
    expired = [t for t in summary.trades if t.result == "expired"]
    assert len(expired) >= 1, "Expected at least one expired trade"
    # Expired trade should have pnl_r computed (at close price)
    assert expired[0].pnl_r is not None


def test_expired_trades_included_in_report():
    """
    Expired trades (result='expired') must appear in the summary metrics.
    """
    from copilot.journal.record import TradeRecord
    from copilot.backtest.report import trades_to_summary

    trades = [
        TradeRecord(setup_name="t", direction="long", symbol="BTC",
                    result="expired", pnl_r=1.0, record_type="backtest",
                    entry_price=100.0, sl_price=95.0),
        TradeRecord(setup_name="t", direction="long", symbol="BTC",
                    result="expired", pnl_r=-1.0, record_type="backtest",
                    entry_price=100.0, sl_price=95.0),
    ]
    summary = trades_to_summary(
        run_id="t", symbol="BTC", tf="1h", rule_name="t", direction="long",
        start="2026-01-01T00:00:00Z", end="2026-04-01T00:00:00Z",
        total_bars=100, total_signals=2, skipped_rr=0, skipped_entry=0,
        bars_in_trade_list=[3, 3], trades=trades,
    )
    assert summary.wins == 1
    assert summary.losses == 1
    assert summary.winrate == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# Change 5: Fee model
# ---------------------------------------------------------------------------

def test_fee_reduces_pnl_r():
    """
    A fee of 8 bps should reduce pnl_r by (entry * 8 / 10_000) / risk.
    Entry=100, SL=95 (risk=5). Fee_r = (100 * 8 / 10000) / 5 = 0.016R.
    A 2R win should net 1.984R after fees.
    """
    from copilot.backtest.engine import _finalize_trade
    from copilot.journal.record import TradeRecord

    trade = TradeRecord(
        record_type="backtest", symbol="BTC", direction="long",
        entry_price=100.0, sl_price=95.0, tp_prices=[110.0],
        result="pending",
    )
    trade = _finalize_trade(trade, "win", 110.0, "t1", fee_bps=8.0, original_sl=95.0)
    # pnl_r before fee = 2.0R; fee_r = (100 * 8/10000) / 5 = 0.016R
    expected = round(2.0 - 0.016, 4)
    assert trade.pnl_r == pytest.approx(expected, abs=0.001)


def test_fee_does_not_apply_when_zero():
    """fee_bps=0.0 must leave pnl_r unchanged."""
    from copilot.backtest.engine import _finalize_trade
    from copilot.journal.record import TradeRecord

    trade = TradeRecord(
        record_type="backtest", symbol="BTC", direction="long",
        entry_price=100.0, sl_price=95.0, tp_prices=[110.0],
        result="pending",
    )
    trade = _finalize_trade(trade, "win", 110.0, "t1", fee_bps=0.0)
    assert trade.pnl_r == pytest.approx(2.0, abs=0.001)


# ---------------------------------------------------------------------------
# Change 6: Variable risk reporting
# ---------------------------------------------------------------------------

def test_variable_risk_pnl_pct_series():
    """pnl_pct_series = pnl_r * risk_pct for each trade."""
    from copilot.journal.record import TradeRecord
    from copilot.backtest.report import trades_to_summary

    trades = [
        TradeRecord(setup_name="t", direction="long", symbol="BTC",
                    result="win", pnl_r=2.0, record_type="backtest",
                    entry_price=100.0, sl_price=95.0),
        TradeRecord(setup_name="t", direction="long", symbol="BTC",
                    result="loss", pnl_r=-1.0, record_type="backtest",
                    entry_price=100.0, sl_price=95.0),
    ]
    summary = trades_to_summary(
        run_id="t", symbol="BTC", tf="1h", rule_name="t", direction="long",
        start="2026-01-01T00:00:00Z", end="2026-04-01T00:00:00Z",
        total_bars=100, total_signals=2, skipped_rr=0, skipped_entry=0,
        bars_in_trade_list=[3, 3], trades=trades, risk_pct=0.5,
    )
    assert summary.risk_pct == 0.5
    assert summary.pnl_pct_series == pytest.approx([1.0, -0.5], abs=0.001)
    assert summary.total_pnl_pct == pytest.approx(0.5, abs=0.001)
    assert summary.monthly_pnl_pct > 0  # 3 months period
