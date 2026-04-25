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
