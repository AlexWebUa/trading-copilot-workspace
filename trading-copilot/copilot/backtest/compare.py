"""
Comparison runner — Phase 6.

compare_rules   — run multiple SetupRules on the same dataset, ranked by PF
walk_forward    — train/test split with no data leakage
ablate_conditions — remove each condition one-by-one to rank their importance
print_comparison  — ASCII table output
print_ablation    — condition importance table
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from copilot.backtest.engine import BacktestEngine, BacktestSummary, _needs_delta
from copilot.backtest.rules import SetupRule

import logging
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ComparisonRow
# ---------------------------------------------------------------------------

@dataclass
class ComparisonRow:
    rule_name: str
    direction: str
    n_trades: int
    winrate: float
    profit_factor: float
    expectancy: float          # in R
    avg_winner_r: float
    avg_loser_r: float
    max_consec_losses: int
    avg_bars_in_trade: float
    skipped_rr: int
    skipped_entry: int
    sufficient_data: bool      # n_trades >= min_trades


# ---------------------------------------------------------------------------
# AblationRow
# ---------------------------------------------------------------------------

@dataclass
class AblationRow:
    condition_idx: int
    detector: str
    field: str
    op: str
    value: Any
    n_trades_full: int
    n_trades_ablated: int
    pf_full: float
    pf_ablated: float
    pf_delta: float            # pf_full - pf_ablated (positive = condition helps)
    verdict: str               # "load_bearing" | "helpful" | "neutral" | "noise"


# ---------------------------------------------------------------------------
# compare_rules
# ---------------------------------------------------------------------------

def compare_rules(
    rules: list[SetupRule],
    symbol: str,
    tf: str,
    bars: int = 2000,
    start: str | None = None,
    end: str | None = None,
    min_trades: int = 20,
    write_journal: bool = False,
    source=None,
) -> list[ComparisonRow]:
    """
    Fetch OHLCV data ONCE, then run BacktestEngine on each rule sequentially.

    If any rule needs delta columns, the shared DataFrame is fetched with delta
    (all OHLCV-only rules simply ignore the extra columns).

    Returns ComparisonRows sorted by profit_factor desc
    (rows with insufficient data are appended at the end).
    """
    if not rules:
        return []

    # Fetch data once
    df = _fetch_shared_df(rules, symbol, tf, bars, start, end, source)
    if df.empty:
        return [_row_from_summary(_empty_summary_for_rule(r, symbol, tf), min_trades) for r in rules]

    rows: list[ComparisonRow] = []
    for rule in rules:
        engine = BacktestEngine(
            source=_WrappedDFSource(df),
            detector_registry=None,
        )
        try:
            rule.validate()
            summary = engine.run(
                symbol=symbol,
                tf=tf,
                rule=rule,
                bars=bars,
                start=start,
                end=end,
                write_journal=write_journal,
            )
        except Exception as exc:
            print(f"  [compare] rule '{rule.name}' raised: {exc}")
            summary = _empty_summary_for_rule(rule, symbol, tf)

        rows.append(_row_from_summary(summary, min_trades))

    # Sort: sufficient data first, then by PF desc; insufficient data appended by PF desc too
    sufficient = sorted([r for r in rows if r.sufficient_data], key=lambda r: -r.profit_factor)
    insufficient = sorted([r for r in rows if not r.sufficient_data], key=lambda r: -r.profit_factor)
    return sufficient + insufficient


# ---------------------------------------------------------------------------
# walk_forward
# ---------------------------------------------------------------------------

def walk_forward(
    rule: SetupRule,
    symbol: str,
    tf: str,
    total_bars: int = 2000,
    test_fraction: float = 0.25,
    source=None,
) -> tuple[BacktestSummary, BacktestSummary]:
    """
    Split total_bars into train (1-test_fraction) and test (test_fraction) windows.
    Both windows are non-overlapping; the test window is strictly after the train window.

    Returns (train_summary, test_summary).
    """
    df = _fetch_shared_df([rule], symbol, tf, total_bars, None, None, source)

    train_bars = int(len(df) * (1 - test_fraction))
    train_df = df.iloc[:train_bars]
    test_df = df.iloc[train_bars:]

    train_summary = _run_on_df(rule, symbol, tf, train_df)
    test_summary = _run_on_df(rule, symbol, tf, test_df)

    return train_summary, test_summary


# ---------------------------------------------------------------------------
# ablate_conditions
# ---------------------------------------------------------------------------

def ablate_conditions(
    rule: SetupRule,
    symbol: str,
    tf: str,
    bars: int = 2000,
    source=None,
) -> list[AblationRow]:
    """
    For each condition in the rule: re-run the rule with that condition removed.
    Returns rows sorted by pf_delta desc (most important conditions first).

    Verdict:
      pf_delta >= 0.5  → "load_bearing"
      pf_delta >= 0.1  → "helpful"
      pf_delta >= -0.1 → "neutral"
      pf_delta < -0.1  → "noise"  (removing it improves PF → condition hurts)
    """
    df = _fetch_shared_df([rule], symbol, tf, bars, None, None, source)

    # Full-rule baseline
    full_summary = _run_on_df(rule, symbol, tf, df)
    pf_full = full_summary.profit_factor
    n_full = full_summary.total_trades

    rows: list[AblationRow] = []
    for idx, cond in enumerate(rule.conditions):
        ablated_conditions = [c for j, c in enumerate(rule.conditions) if j != idx]
        if not ablated_conditions:
            # Only one condition — can't ablate without removing all conditions
            ablated_pf = 0.0
            n_ablated = 0
        else:
            from dataclasses import replace as dc_replace
            ablated_rule = SetupRule(
                name=f"{rule.name}_ablate_{idx}",
                direction=rule.direction,
                conditions=ablated_conditions,
                entry_after=rule.entry_after,
                sl_logic=rule.sl_logic,
                tp_logic=rule.tp_logic,
                required_session=rule.required_session,
                required_killzone=rule.required_killzone,
            )
            ablated_summary = _run_on_df(ablated_rule, symbol, tf, df)
            ablated_pf = ablated_summary.profit_factor
            n_ablated = ablated_summary.total_trades

        pf_delta = round(pf_full - ablated_pf, 3)
        verdict = _ablation_verdict(pf_delta)

        rows.append(AblationRow(
            condition_idx=idx,
            detector=cond.detector,
            field=cond.field,
            op=cond.op,
            value=cond.value,
            n_trades_full=n_full,
            n_trades_ablated=n_ablated,
            pf_full=round(pf_full, 3),
            pf_ablated=round(ablated_pf, 3),
            pf_delta=pf_delta,
            verdict=verdict,
        ))

    return sorted(rows, key=lambda r: -r.pf_delta)


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def print_comparison(rows: list[ComparisonRow], title: str = "") -> None:
    """
    Print a ranked comparison table to stdout.

    Columns: rank | rule | dir | trades | WR% | PF | E(R) | avgW | avgL | maxCL
    Flags:
      (*) n_trades < min_trades threshold (insufficient data)
      (!) profit_factor < 1.0  (losing strategy)
    """
    if title:
        print(f"\n{'='*72}")
        print(f"  {title}")
        print(f"{'='*72}")

    if not rows:
        print("  (no results)")
        return

    header = f"{'Rank':>4}  {'Rule':<34} {'Dir':>5}  {'N':>5}  {'WR%':>6}  {'PF':>6}  {'E(R)':>6}  {'avgW':>6}  {'avgL':>6}  {'mCL':>4}"
    print(header)
    print("-" * len(header))

    for rank, row in enumerate(rows, 1):
        flags = ""
        if not row.sufficient_data:
            flags += "*"
        if row.profit_factor < 1.0:
            flags += "!"
        flag_str = f" [{flags}]" if flags else ""

        rule_display = row.rule_name[:32] + flag_str
        print(
            f"{rank:>4}  {rule_display:<34} {row.direction:>5}  {row.n_trades:>5}"
            f"  {row.winrate*100:>5.1f}%  {row.profit_factor:>6.2f}  {row.expectancy:>+6.2f}"
            f"  {row.avg_winner_r:>6.2f}  {row.avg_loser_r:>6.2f}  {row.max_consec_losses:>4}"
        )

    print()
    print("  Flags: (*) < min_trades threshold  (!) PF < 1.0")


def print_ablation(rows: list[AblationRow], rule_name: str = "") -> None:
    """Print condition importance table for a single rule."""
    header = f"{'#':>3}  {'Detector':<32} {'Field':<24} {'Op':>8}  {'PF_full':>7}  {'PF_abl':>7}  {'ΔPNL':>7}  {'Verdict'}"
    print(f"\n  Ablation: {rule_name}")
    print(header)
    print("-" * len(header))
    for row in rows:
        val_str = str(row.value)[:12] if row.value is not None else "—"
        print(
            f"{row.condition_idx:>3}  {row.detector:<32} {row.field:<24}"
            f" {row.op:>8}  {row.pf_full:>7.3f}  {row.pf_ablated:>7.3f}"
            f"  {row.pf_delta:>+7.3f}  {row.verdict}"
        )
    print()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _fetch_shared_df(
    rules: list[SetupRule],
    symbol: str,
    tf: str,
    bars: int,
    start: str | None,
    end: str | None,
    source,
) -> pd.DataFrame:
    """
    Fetch a single DataFrame for all rules.
    If any rule needs delta columns, fetch with delta (others ignore extra cols).
    """
    any_delta = any(_needs_delta(r) for r in rules)

    if source is not None:
        # Caller supplied a pre-built source (tests / custom)
        return source.get_ohlc(symbol, tf, bars)

    if any_delta:
        try:
            from copilot.data.binance import fetch_ohlcv_with_delta
            return fetch_ohlcv_with_delta(symbol, tf, bars, market="futures")
        except Exception:
            logger.warning("Delta fetch failed for %s/%s; falling back to standard OHLCV", symbol, tf, exc_info=True)

    from copilot.data.binance import BinanceSource
    src = BinanceSource()
    return src.get_ohlc(symbol, tf, bars)


class _WrappedDFSource:
    """Thin source wrapper that always returns the same pre-fetched DataFrame."""

    def __init__(self, df: pd.DataFrame):
        self._df = df

    def get_ohlc(self, symbol: str, tf: str, bars: int = 500) -> pd.DataFrame:
        return self._df.copy()


def _run_on_df(rule: SetupRule, symbol: str, tf: str, df: pd.DataFrame) -> BacktestSummary:
    """Run engine on a specific DataFrame slice."""
    engine = BacktestEngine(source=_WrappedDFSource(df), detector_registry=None)
    try:
        rule.validate()
        return engine.run(symbol=symbol, tf=tf, rule=rule, bars=len(df), write_journal=False)
    except Exception as exc:
        print(f"  [compare] rule '{rule.name}' raised: {exc}")
        return _empty_summary_for_rule(rule, symbol, tf)


def _empty_summary_for_rule(rule: SetupRule, symbol: str, tf: str) -> BacktestSummary:
    from copilot.backtest.engine import BacktestSummary
    import uuid
    return BacktestSummary(
        run_id=str(uuid.uuid4()),
        symbol=symbol,
        tf=tf,
        start="—",
        end="—",
        rule_name=rule.name,
        direction=rule.direction,
    )


def _row_from_summary(summary: BacktestSummary, min_trades: int) -> ComparisonRow:
    completed = summary.wins + summary.losses
    return ComparisonRow(
        rule_name=summary.rule_name,
        direction=summary.direction,
        n_trades=completed,
        winrate=summary.winrate,
        profit_factor=summary.profit_factor,
        expectancy=summary.expectancy,
        avg_winner_r=summary.avg_winner_r,
        avg_loser_r=summary.avg_loser_r,
        max_consec_losses=summary.max_consec_losses,
        avg_bars_in_trade=summary.avg_bars_in_trade,
        skipped_rr=summary.skipped_rr,
        skipped_entry=summary.skipped_entry,
        sufficient_data=completed >= min_trades,
    )


def _ablation_verdict(pf_delta: float) -> str:
    if pf_delta >= 0.5:
        return "load_bearing"
    if pf_delta >= 0.1:
        return "helpful"
    if pf_delta >= -0.1:
        return "neutral"
    return "noise"
