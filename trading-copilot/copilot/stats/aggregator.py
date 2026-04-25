"""
Statistics aggregator — Phase 6.

Consumes TradeRecord objects from the journal (both record_type="trade" and
"backtest") and computes grouped performance metrics.

compute_stats        — group records by setup/tool/session/dow/etc., compute metrics
tool_effectiveness   — measure winrate with vs without each tool in tools_confirmed
print_stats          — ASCII table output
print_tool_effectiveness — ASCII table for tool analysis
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from copilot.journal.record import TradeRecord

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_VALID_GROUP_BY = frozenset(
    {"setup", "tool", "session", "dow", "account", "record_type"}
)


# ---------------------------------------------------------------------------
# StatsRow
# ---------------------------------------------------------------------------

@dataclass
class StatsRow:
    group_value: str        # e.g. "sweep_bos_long", "london_open", "Tuesday"
    n_trades: int
    winrate: float
    profit_factor: float
    expectancy: float       # mean R per closed trade
    avg_winner_r: float
    avg_loser_r: float
    max_drawdown_r: float   # max consecutive-loss streak in R
    sufficient_data: bool   # n_trades >= min_trades


# ---------------------------------------------------------------------------
# ToolEffectivenessRow
# ---------------------------------------------------------------------------

@dataclass
class ToolEffectivenessRow:
    tool: str
    n_with: int
    n_without: int
    winrate_with: float
    winrate_without: float
    delta_winrate: float    # positive = tool helps
    verdict: str            # "positive" | "neutral" | "negative"


# ---------------------------------------------------------------------------
# compute_stats
# ---------------------------------------------------------------------------

def compute_stats(
    records: list[TradeRecord] | None = None,
    *,
    path: Path | None = None,
    group_by: str = "setup",
    record_type: str | None = None,
    setup_name: str | None = None,
    min_trades: int = 5,
) -> list[StatsRow]:
    """
    Load records (from path or list), apply filters, group by dimension,
    compute performance metrics per group.

    group_by options:
      "setup"       — one row per setup_name
      "tool"        — one row per tool in tools_confirmed (conditional winrate)
      "session"     — one row per session label
      "dow"         — one row per day of week (0=Mon, 6=Sun)
      "account"     — one row per account_type
      "record_type" — one row per record_type ("trade" vs "backtest")

    Returns rows sorted by profit_factor desc.
    """
    if group_by not in _VALID_GROUP_BY:
        raise ValueError(f"group_by must be one of {sorted(_VALID_GROUP_BY)}, got {group_by!r}")

    recs = _load_records(records, path)

    # Apply filters
    if record_type is not None:
        recs = [r for r in recs if r.record_type == record_type]
    if setup_name is not None:
        recs = [r for r in recs if r.setup_name == setup_name]

    # Keep only closed trades for metrics
    closed = [r for r in recs if r.result in ("win", "loss", "be")]

    if group_by == "tool":
        return _stats_by_tool(closed, min_trades)

    # Group by the requested dimension
    groups: dict[str, list[TradeRecord]] = defaultdict(list)
    for rec in closed:
        key = _group_key(rec, group_by)
        if key is not None:
            groups[key].append(rec)

    rows = [
        _compute_group_stats(key, group_recs, min_trades)
        for key, group_recs in groups.items()
    ]
    return sorted(rows, key=lambda r: -r.profit_factor)


# ---------------------------------------------------------------------------
# tool_effectiveness
# ---------------------------------------------------------------------------

def tool_effectiveness(
    records: list[TradeRecord] | None = None,
    *,
    path: Path | None = None,
) -> list[ToolEffectivenessRow]:
    """
    For each tool in tools_confirmed: compare winrate on trades where the tool
    WAS confirmed vs trades where it was NOT confirmed.

    delta_winrate = winrate_with - winrate_without
    """
    recs = _load_records(records, path)
    closed = [r for r in recs if r.result in ("win", "loss")]

    # Collect all unique tools
    all_tools: set[str] = set()
    for rec in closed:
        all_tools.update(rec.tools_confirmed or [])

    rows: list[ToolEffectivenessRow] = []
    for tool in sorted(all_tools):
        with_tool = [r for r in closed if tool in (r.tools_confirmed or [])]
        without_tool = [r for r in closed if tool not in (r.tools_confirmed or [])]

        wr_with = _winrate(with_tool)
        wr_without = _winrate(without_tool)
        delta = round(wr_with - wr_without, 4)

        if delta >= 0.05:
            verdict = "positive"
        elif delta <= -0.05:
            verdict = "negative"
        else:
            verdict = "neutral"

        rows.append(ToolEffectivenessRow(
            tool=tool,
            n_with=len(with_tool),
            n_without=len(without_tool),
            winrate_with=round(wr_with, 4),
            winrate_without=round(wr_without, 4),
            delta_winrate=delta,
            verdict=verdict,
        ))

    return sorted(rows, key=lambda r: -r.delta_winrate)


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def print_stats(rows: list[StatsRow], group_by: str = "") -> None:
    """Print a stats table to stdout."""
    label = f" grouped by {group_by}" if group_by else ""
    print(f"\n{'='*70}")
    print(f"  Performance stats{label}")
    print(f"{'='*70}")

    if not rows:
        print("  (no data)")
        return

    header = f"{'Group':<26} {'N':>5}  {'WR%':>6}  {'PF':>6}  {'E(R)':>6}  {'avgW':>6}  {'avgL':>6}  {'MDD':>7}"
    print(header)
    print("-" * len(header))

    for row in rows:
        flag = " " if row.sufficient_data else "*"
        print(
            f"{flag}{row.group_value:<25} {row.n_trades:>5}"
            f"  {row.winrate*100:>5.1f}%  {row.profit_factor:>6.2f}"
            f"  {row.expectancy:>+6.2f}  {row.avg_winner_r:>6.2f}"
            f"  {row.avg_loser_r:>6.2f}  {row.max_drawdown_r:>7.2f}"
        )

    print()
    print("  * insufficient data (< min_trades)")


def print_tool_effectiveness(rows: list[ToolEffectivenessRow]) -> None:
    """Print tool effectiveness table."""
    print(f"\n{'='*70}")
    print("  Tool Effectiveness")
    print(f"{'='*70}")

    if not rows:
        print("  (no data)")
        return

    header = f"{'Tool':<32} {'N_w':>5}  {'N_wo':>5}  {'WR_w':>7}  {'WR_wo':>7}  {'ΔWR':>7}  {'Verdict'}"
    print(header)
    print("-" * len(header))

    for row in rows:
        print(
            f"{row.tool:<32} {row.n_with:>5}  {row.n_without:>5}"
            f"  {row.winrate_with*100:>6.1f}%  {row.winrate_without*100:>6.1f}%"
            f"  {row.delta_winrate*100:>+6.1f}%  {row.verdict}"
        )
    print()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _load_records(
    records: list[TradeRecord] | None,
    path: Path | None,
) -> list[TradeRecord]:
    if records is not None:
        return list(records)
    if path is not None:
        from copilot.journal.reader import load_all
        return load_all(path=path)
    return []


def _group_key(rec: TradeRecord, group_by: str) -> str | None:
    if group_by == "setup":
        return rec.setup_name or "unknown"
    if group_by == "session":
        return rec.session or "unknown"
    if group_by == "dow":
        return _DAYS[rec.day_of_week % 7]
    if group_by == "account":
        return rec.account_type or "unknown"
    if group_by == "record_type":
        return rec.record_type or "unknown"
    return None


def _compute_group_stats(
    key: str,
    recs: list[TradeRecord],
    min_trades: int,
) -> StatsRow:
    wins = [r for r in recs if r.result == "win"]
    losses = [r for r in recs if r.result == "loss"]
    n = len(wins) + len(losses)

    winrate = len(wins) / n if n > 0 else 0.0

    winner_rs = [r.pnl_r for r in wins if r.pnl_r is not None]
    loser_rs = [r.pnl_r for r in losses if r.pnl_r is not None]

    gross_win = sum(winner_rs) if winner_rs else 0.0
    gross_loss = abs(sum(loser_rs)) if loser_rs else 0.0
    pf = gross_win / gross_loss if gross_loss > 1e-10 else (float("inf") if gross_win > 0 else 0.0)

    all_r = winner_rs + loser_rs
    expectancy = sum(all_r) / len(all_r) if all_r else 0.0

    avg_winner = sum(winner_rs) / len(winner_rs) if winner_rs else 0.0
    avg_loser = sum(loser_rs) / len(loser_rs) if loser_rs else 0.0

    mdd = _max_consecutive_drawdown(all_r)

    return StatsRow(
        group_value=key,
        n_trades=n,
        winrate=round(winrate, 4),
        profit_factor=round(pf, 3),
        expectancy=round(expectancy, 3),
        avg_winner_r=round(avg_winner, 3),
        avg_loser_r=round(avg_loser, 3),
        max_drawdown_r=round(mdd, 3),
        sufficient_data=n >= min_trades,
    )


def _stats_by_tool(closed: list[TradeRecord], min_trades: int) -> list[StatsRow]:
    """Compute per-tool conditional stats: only trades where tool was confirmed."""
    tool_map: dict[str, list[TradeRecord]] = defaultdict(list)
    for rec in closed:
        for tool in rec.tools_confirmed or []:
            tool_map[tool].append(rec)

    rows = [
        _compute_group_stats(tool, recs, min_trades)
        for tool, recs in tool_map.items()
    ]
    return sorted(rows, key=lambda r: -r.profit_factor)


def _winrate(recs: list[TradeRecord]) -> float:
    wins = sum(1 for r in recs if r.result == "win")
    total = sum(1 for r in recs if r.result in ("win", "loss"))
    return wins / total if total > 0 else 0.0


def _max_consecutive_drawdown(pnl_series: list[float]) -> float:
    """Sum of the worst consecutive-loss streak in R (always non-negative)."""
    max_dd = 0.0
    streak = 0.0
    for pnl in pnl_series:
        if pnl < 0:
            streak += abs(pnl)
            max_dd = max(max_dd, streak)
        else:
            streak = 0.0
    return max_dd
