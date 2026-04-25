"""Tests for copilot/stats/aggregator.py"""

from __future__ import annotations

import pytest

from copilot.journal.record import TradeRecord
from copilot.stats.aggregator import (
    StatsRow,
    ToolEffectivenessRow,
    compute_stats,
    print_stats,
    print_tool_effectiveness,
    tool_effectiveness,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _t(
    result: str,
    pnl: float | None = None,
    setup: str = "test_setup",
    session: str = "london_open",
    dow: int = 0,
    account: str = "demo",
    record_type: str = "backtest",
    tools: list[str] | None = None,
) -> TradeRecord:
    return TradeRecord(
        record_type=record_type,
        setup_name=setup,
        direction="long",
        result=result,
        pnl_r=pnl,
        session=session,
        day_of_week=dow,
        account_type=account,
        entry_price=100.0,
        sl_price=95.0,
        tp_prices=[110.0],
        tools_confirmed=tools or [],
    )


# ---------------------------------------------------------------------------
# compute_stats — by setup
# ---------------------------------------------------------------------------

def test_compute_stats_by_setup():
    """2 distinct setups → 2 StatsRow returned."""
    records = (
        [_t("win", 2.0, setup="setup_a")] * 3
        + [_t("loss", -1.0, setup="setup_a")] * 2
        + [_t("win", 2.0, setup="setup_b")] * 4
        + [_t("loss", -1.0, setup="setup_b")] * 1
    )
    rows = compute_stats(records=records, group_by="setup", min_trades=1)
    names = {r.group_value for r in rows}
    assert "setup_a" in names
    assert "setup_b" in names
    assert len(rows) == 2


def test_compute_stats_by_tool():
    """Trades with 'detect_fvg' in tools_confirmed → row for that tool."""
    records = [
        _t("win", 2.0, tools=["detect_fvg", "detect_bos"]),
        _t("win", 2.0, tools=["detect_fvg"]),
        _t("loss", -1.0, tools=["detect_fvg"]),
        _t("win", 2.0, tools=["detect_bos"]),
        _t("loss", -1.0, tools=[]),
    ]
    rows = compute_stats(records=records, group_by="tool", min_trades=1)
    tool_names = {r.group_value for r in rows}
    assert "detect_fvg" in tool_names
    assert "detect_bos" in tool_names


def test_compute_stats_by_session():
    """london_open and ny_am sessions → 2 separate StatsRows."""
    records = (
        [_t("win", 2.0, session="london_open")] * 3
        + [_t("loss", -1.0, session="london_open")] * 1
        + [_t("win", 2.0, session="ny_am")] * 2
        + [_t("loss", -1.0, session="ny_am")] * 2
    )
    rows = compute_stats(records=records, group_by="session", min_trades=1)
    sessions = {r.group_value for r in rows}
    assert "london_open" in sessions
    assert "ny_am" in sessions
    assert len(rows) == 2


def test_compute_stats_filters_record_type():
    """record_type='backtest' filter excludes live trade records."""
    records = [
        _t("win", 2.0, record_type="backtest"),
        _t("win", 2.0, record_type="backtest"),
        _t("win", 2.0, record_type="trade"),    # should be excluded
        _t("loss", -1.0, record_type="trade"),   # should be excluded
    ]
    rows = compute_stats(records=records, group_by="record_type",
                         record_type="backtest", min_trades=1)
    assert len(rows) == 1
    assert rows[0].group_value == "backtest"
    assert rows[0].n_trades == 2  # only 2 backtest records


def test_insufficient_data_flagged():
    """3 trades < min_trades=5 → sufficient_data=False."""
    records = [_t("win", 2.0)] * 2 + [_t("loss", -1.0)] * 1
    rows = compute_stats(records=records, group_by="setup", min_trades=5)
    assert len(rows) == 1
    assert rows[0].sufficient_data is False


# ---------------------------------------------------------------------------
# Metric calculations
# ---------------------------------------------------------------------------

def test_winrate_calculation():
    """3W/2L = 0.6 winrate."""
    records = [_t("win", 2.0)] * 3 + [_t("loss", -1.0)] * 2
    rows = compute_stats(records=records, group_by="setup", min_trades=1)
    assert len(rows) == 1
    assert rows[0].winrate == pytest.approx(0.6, abs=0.01)
    assert rows[0].n_trades == 5


def test_profit_factor_calculation():
    """2W@2R + 1L@-1R → PF = 4.0 / 1.0 = 4.0."""
    records = [_t("win", 2.0), _t("win", 2.0), _t("loss", -1.0)]
    rows = compute_stats(records=records, group_by="setup", min_trades=1)
    assert rows[0].profit_factor == pytest.approx(4.0, rel=0.01)


def test_compute_stats_empty_records():
    """Empty records list → empty rows list, no crash."""
    rows = compute_stats(records=[], group_by="setup")
    assert rows == []


def test_compute_stats_invalid_group_by():
    """Invalid group_by raises ValueError."""
    with pytest.raises(ValueError):
        compute_stats(records=[], group_by="invalid_dimension")


# ---------------------------------------------------------------------------
# tool_effectiveness
# ---------------------------------------------------------------------------

def test_tool_effectiveness_delta_positive():
    """
    'detect_fvg' confirmed → 8W/2L (80% WR).
    'detect_fvg' absent → 2W/8L (20% WR).
    Δ = 0.6 → verdict 'positive'.
    """
    with_fvg = [_t("win", 2.0, tools=["detect_fvg"])] * 8 + [_t("loss", -1.0, tools=["detect_fvg"])] * 2
    without_fvg = [_t("win", 2.0, tools=[])] * 2 + [_t("loss", -1.0, tools=[])] * 8

    rows = tool_effectiveness(records=with_fvg + without_fvg)
    fvg_row = next((r for r in rows if r.tool == "detect_fvg"), None)
    assert fvg_row is not None
    assert fvg_row.delta_winrate == pytest.approx(0.6, abs=0.01)
    assert fvg_row.verdict == "positive"
    assert fvg_row.n_with == 10
    assert fvg_row.n_without == 10


def test_tool_effectiveness_negative_delta():
    """
    Tool confirmed → 2W/8L (20% WR).
    Tool absent → 8W/2L (80% WR).
    Δ = -0.6 → verdict 'negative'.
    """
    with_tool = [_t("win", 2.0, tools=["bad_tool"])] * 2 + [_t("loss", -1.0, tools=["bad_tool"])] * 8
    without_tool = [_t("win", 2.0, tools=[])] * 8 + [_t("loss", -1.0, tools=[])] * 2

    rows = tool_effectiveness(records=with_tool + without_tool)
    tool_row = next((r for r in rows if r.tool == "bad_tool"), None)
    assert tool_row is not None
    assert tool_row.delta_winrate < -0.05
    assert tool_row.verdict == "negative"


def test_tool_effectiveness_empty():
    """Empty records → empty rows, no crash."""
    rows = tool_effectiveness(records=[])
    assert rows == []


# ---------------------------------------------------------------------------
# Print helpers (smoke tests)
# ---------------------------------------------------------------------------

def test_print_stats_no_crash():
    """print_stats with both empty and populated rows must not raise."""
    print_stats([], group_by="setup")
    rows = [StatsRow(
        group_value="test_setup",
        n_trades=10,
        winrate=0.6,
        profit_factor=2.0,
        expectancy=0.8,
        avg_winner_r=2.0,
        avg_loser_r=-1.0,
        max_drawdown_r=3.0,
        sufficient_data=True,
    )]
    print_stats(rows, group_by="setup")


def test_print_tool_effectiveness_no_crash():
    """print_tool_effectiveness with valid rows must not raise."""
    print_tool_effectiveness([])
    rows = [ToolEffectivenessRow(
        tool="detect_fvg",
        n_with=10, n_without=10,
        winrate_with=0.8, winrate_without=0.2,
        delta_winrate=0.6, verdict="positive",
    )]
    print_tool_effectiveness(rows)
