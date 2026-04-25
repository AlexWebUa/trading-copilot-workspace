"""Tests for copilot/backtest/compare.py"""

from __future__ import annotations

import io
import sys
from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from copilot.backtest.compare import (
    AblationRow,
    ComparisonRow,
    ablate_conditions,
    compare_rules,
    print_ablation,
    print_comparison,
    walk_forward,
)
from copilot.backtest.rules import Condition, SetupRule


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_df(n: int = 200, base: float = 100.0) -> pd.DataFrame:
    ts = [datetime(2026, 4, 1, 10, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(n)]
    rows = [{"open": base, "high": base + 1.0, "low": base - 1.0, "close": base, "volume": 100.0}
            for _ in range(n)]
    return pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))


class _StaticSource:
    """Returns the same DataFrame regardless of symbol/tf/bars."""
    def __init__(self, df: pd.DataFrame):
        self._df = df
        self.call_count = 0

    def get_ohlc(self, symbol: str, tf: str, bars: int = 500) -> pd.DataFrame:
        self.call_count += 1
        return self._df.copy()


def _always_true_rule(name: str = "always_true") -> SetupRule:
    return SetupRule(
        name=name,
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="signal_close",
        sl_logic="pct:5.0",
        tp_logic="rr:2.0",
        required_session=None,
    )


def _never_true_rule(name: str = "never_true") -> SetupRule:
    """A rule whose condition can never pass (count_active < -1 is impossible)."""
    return SetupRule(
        name=name,
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "lt", -1)],
        entry_after="next_open",
        sl_logic="pct:5.0",
        tp_logic="rr:2.0",
        required_session=None,
    )


# ---------------------------------------------------------------------------
# compare_rules
# ---------------------------------------------------------------------------

def test_compare_returns_one_row_per_rule():
    """N rules → exactly N ComparisonRow objects returned."""
    df = _make_df(n=200)
    source = _StaticSource(df)
    rules = [_always_true_rule("rule_a"), _always_true_rule("rule_b"), _never_true_rule("rule_c")]
    rows = compare_rules(rules, "BTCUSDT", "1h", bars=200, source=source)
    assert len(rows) == 3


def test_compare_sorted_by_profit_factor():
    """Sufficient-data rows must be sorted by profit_factor descending."""
    df = _make_df(n=200)
    source = _StaticSource(df)
    # Both rules same conditions → same PF, but order must be consistent
    rules = [_always_true_rule("a"), _always_true_rule("b")]
    rows = compare_rules(rules, "BTCUSDT", "1h", bars=200, source=source, min_trades=0)
    sufficient = [r for r in rows if r.sufficient_data]
    for i in range(len(sufficient) - 1):
        assert sufficient[i].profit_factor >= sufficient[i + 1].profit_factor


def test_insufficient_data_flagged():
    """Rule with 0 trades gets sufficient_data=False."""
    df = _make_df(n=200)
    source = _StaticSource(df)
    rules = [_never_true_rule("zero_trades")]
    rows = compare_rules(rules, "BTCUSDT", "1h", bars=200, source=source, min_trades=20)
    assert len(rows) == 1
    assert rows[0].sufficient_data is False
    assert rows[0].n_trades == 0


def test_compare_shares_single_fetch():
    """
    source.get_ohlc is called exactly once for compare_rules (shared DataFrame).
    The engine wraps the passed df via _WrappedDFSource, but that source's
    get_ohlc call serves all rules from the shared df.
    """
    df = _make_df(n=200)
    source = _StaticSource(df)
    rules = [_always_true_rule("a"), _always_true_rule("b"), _never_true_rule("c")]
    compare_rules(rules, "BTCUSDT", "1h", bars=200, source=source)
    # The shared fetch happens once through source; each engine sees _WrappedDFSource
    assert source.call_count == 1


def test_compare_empty_rules_returns_empty():
    """Empty rules list → empty result."""
    rows = compare_rules([], "BTCUSDT", "1h", bars=200)
    assert rows == []


def test_compare_row_fields():
    """ComparisonRow has all required fields with correct types."""
    df = _make_df(n=200)
    source = _StaticSource(df)
    rows = compare_rules([_always_true_rule()], "BTCUSDT", "1h", bars=200, source=source)
    assert len(rows) == 1
    r = rows[0]
    assert isinstance(r.rule_name, str)
    assert isinstance(r.direction, str)
    assert isinstance(r.n_trades, int)
    assert 0.0 <= r.winrate <= 1.0
    assert r.profit_factor >= 0.0
    assert isinstance(r.sufficient_data, bool)


# ---------------------------------------------------------------------------
# walk_forward
# ---------------------------------------------------------------------------

def test_walk_forward_two_summaries():
    """walk_forward returns a tuple of two BacktestSummary objects."""
    from copilot.backtest.engine import BacktestSummary
    df = _make_df(n=300)
    source = _StaticSource(df)
    rule = _always_true_rule()
    train_s, test_s = walk_forward(rule, "BTCUSDT", "1h", total_bars=300, source=source)
    assert isinstance(train_s, BacktestSummary)
    assert isinstance(test_s, BacktestSummary)


def test_walk_forward_non_overlapping():
    """
    Train window scans more bars than the test window because it uses 75% of data.
    Also, total bars scanned should not exceed the total data length.
    """
    df = _make_df(n=300)
    source = _StaticSource(df)
    rule = _always_true_rule()
    train_s, test_s = walk_forward(rule, "BTCUSDT", "1h", total_bars=300, source=source)
    # Train covers 225 bars (75%), test covers 75 (25%)
    # total_bars_scanned excludes the leading 50 bars
    assert train_s.total_bars_scanned + test_s.total_bars_scanned <= 300


# ---------------------------------------------------------------------------
# ablate_conditions
# ---------------------------------------------------------------------------

def test_ablate_returns_one_row_per_condition():
    """N conditions → N AblationRow returned."""
    df = _make_df(n=200)
    source = _StaticSource(df)
    rule = SetupRule(
        name="multi_cond",
        direction="long",
        conditions=[
            Condition("detect_fvg", "count_active", "gte", 0),
            Condition("detect_market_structure", "state", "in", ["bullish", "ranging", "bearish"]),
        ],
        entry_after="signal_close",
        sl_logic="pct:5.0",
        tp_logic="rr:2.0",
    )
    rows = ablate_conditions(rule, "BTCUSDT", "1h", bars=200, source=source)
    assert len(rows) == 2


def test_ablate_pf_delta_computed():
    """pf_delta = pf_full - pf_ablated (may be positive or negative)."""
    df = _make_df(n=200)
    source = _StaticSource(df)
    rule = SetupRule(
        name="ablate_test",
        direction="long",
        conditions=[
            Condition("detect_fvg", "count_active", "gte", 0),
            Condition("detect_market_structure", "state", "in", ["bullish", "ranging", "bearish"]),
        ],
        entry_after="signal_close",
        sl_logic="pct:5.0",
        tp_logic="rr:2.0",
    )
    rows = ablate_conditions(rule, "BTCUSDT", "1h", bars=200, source=source)
    for row in rows:
        assert isinstance(row.pf_delta, float)
        # pf_delta = pf_full - pf_ablated
        assert abs(row.pf_delta - (row.pf_full - row.pf_ablated)) < 0.01
        assert row.verdict in ("load_bearing", "helpful", "neutral", "noise")


def test_ablate_verdict_load_bearing():
    """A condition that causes pf_delta >= 0.5 gets verdict 'load_bearing'."""
    from copilot.backtest.compare import _ablation_verdict
    assert _ablation_verdict(0.6) == "load_bearing"
    assert _ablation_verdict(0.5) == "load_bearing"


def test_ablate_verdict_noise():
    """A condition that causes pf_delta < -0.1 gets verdict 'noise'."""
    from copilot.backtest.compare import _ablation_verdict
    assert _ablation_verdict(-0.2) == "noise"
    assert _ablation_verdict(-0.5) == "noise"


# ---------------------------------------------------------------------------
# print helpers (smoke tests)
# ---------------------------------------------------------------------------

def test_print_comparison_no_crash():
    """print_comparison with empty and non-empty lists must not raise."""
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        print_comparison([], title="Empty test")
        rows = [
            ComparisonRow(
                rule_name="test_rule", direction="long",
                n_trades=25, winrate=0.6, profit_factor=2.0,
                expectancy=0.8, avg_winner_r=2.0, avg_loser_r=1.0,
                max_consec_losses=3, avg_bars_in_trade=5.0,
                skipped_rr=2, skipped_entry=1, sufficient_data=True,
            )
        ]
        print_comparison(rows, title="Non-empty test")
    finally:
        sys.stdout = old_stdout
    output = captured.getvalue()
    assert "test_rule" in output


def test_print_ablation_no_crash():
    """print_ablation must not raise for any valid AblationRow list."""
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        rows = [
            AblationRow(
                condition_idx=0, detector="detect_fvg", field="count_active",
                op="gt", value=0, n_trades_full=30, n_trades_ablated=50,
                pf_full=2.5, pf_ablated=1.8, pf_delta=0.7, verdict="load_bearing",
            )
        ]
        print_ablation(rows, "test_rule")
        print_ablation([], "empty_rule")
    finally:
        sys.stdout = old_stdout
    output = captured.getvalue()
    assert "detect_fvg" in output
