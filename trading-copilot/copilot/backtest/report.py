"""
BacktestSummary computation and presentation.

trades_to_summary  — compute all metrics from a list of completed TradeRecords
print_summary      — print human-readable summary to stdout (no rich dependency)
write_summary_to_journal — persist TradeRecords to journal.jsonl
"""

from __future__ import annotations

from pathlib import Path

from copilot.journal.record import TradeRecord
from copilot.journal.writer import append_record


def trades_to_summary(
    run_id: str,
    symbol: str,
    tf: str,
    rule_name: str,
    direction: str,
    start: str,
    end: str,
    total_bars: int,
    total_signals: int,
    skipped_rr: int,
    skipped_entry: int,
    bars_in_trade_list: list[int],
    trades: list[TradeRecord],
    risk_pct: float = 1.0,
) -> "BacktestSummary":  # noqa: F821
    from copilot.backtest.engine import BacktestSummary

    # Change 4: "expired" trades are included and classified by pnl_r sign
    completed = [t for t in trades if t.result in ("win", "loss", "be", "expired")]
    wins = [
        t for t in completed
        if t.result == "win"
        or (t.result == "expired" and (t.pnl_r or 0.0) > 0.01)
    ]
    losses = [
        t for t in completed
        if t.result == "loss"
        or (t.result == "expired" and (t.pnl_r or 0.0) < -0.01)
    ]
    bes = [
        t for t in completed
        if t.result == "be"
        or (t.result == "expired" and abs(t.pnl_r or 0.0) <= 0.01)
    ]

    n_w = len(wins)
    n_l = len(losses)
    n_be = len(bes)
    n_completed = n_w + n_l  # be excluded from winrate denominator

    winrate = round(n_w / n_completed, 4) if n_completed else 0.0

    win_rs = [t.pnl_r for t in wins if t.pnl_r is not None]
    loss_rs = [t.pnl_r for t in losses if t.pnl_r is not None]

    avg_winner_r = round(sum(win_rs) / len(win_rs), 3) if win_rs else 0.0
    avg_loser_r = round(sum(loss_rs) / len(loss_rs), 3) if loss_rs else 0.0

    total_win_r = sum(win_rs)
    total_loss_r = abs(sum(loss_rs)) if loss_rs else 0.0
    profit_factor = round(total_win_r / total_loss_r, 3) if total_loss_r > 0 else (
        float("inf") if total_win_r > 0 else 0.0
    )

    loss_rate = 1.0 - winrate
    expectancy = round(winrate * avg_winner_r + loss_rate * avg_loser_r, 3)

    max_consec = _max_consecutive_losses([t.pnl_r or 0.0 for t in completed])
    pnl_series = [t.pnl_r for t in completed if t.pnl_r is not None]

    avg_bars = round(sum(bars_in_trade_list) / len(bars_in_trade_list), 1) if bars_in_trade_list else 0.0
    max_bars = max(bars_in_trade_list) if bars_in_trade_list else 0

    session_breakdown = _session_breakdown(completed)

    # Change 6: variable risk reporting
    pnl_pct_series = [round(r * risk_pct, 4) for r in pnl_series]
    total_pnl_pct = round(sum(pnl_pct_series), 4)

    # Approximate months in period from timestamps
    months_in_period = _estimate_months(start, end)
    monthly_pnl_pct = round(total_pnl_pct / months_in_period, 4) if months_in_period > 0 else 0.0

    return BacktestSummary(
        run_id=run_id,
        symbol=symbol,
        tf=tf,
        start=start,
        end=end,
        rule_name=rule_name,
        direction=direction,
        total_bars_scanned=total_bars,
        total_signals=total_signals,
        total_trades=len(trades),
        skipped_rr=skipped_rr,
        skipped_entry=skipped_entry,
        wins=n_w,
        losses=n_l,
        breakevens=n_be,
        winrate=winrate,
        avg_winner_r=avg_winner_r,
        avg_loser_r=avg_loser_r,
        expectancy=expectancy,
        profit_factor=profit_factor,
        max_consec_losses=max_consec,
        avg_bars_in_trade=avg_bars,
        max_bars_in_trade=max_bars,
        pnl_r_series=pnl_series,
        session_breakdown=session_breakdown,
        trades=trades,
        risk_pct=risk_pct,
        pnl_pct_series=pnl_pct_series,
        total_pnl_pct=total_pnl_pct,
        monthly_pnl_pct=monthly_pnl_pct,
    )


def print_summary(summary: "BacktestSummary") -> None:  # noqa: F821
    """Print a plain-text backtest summary to stdout."""
    sep = "─" * 47
    rid = summary.run_id[:8]

    print(f"\nBacktest: {summary.rule_name} · {summary.symbol} · {summary.tf}")
    print(f"Run ID  : {rid}  ({summary.start[:10]} → {summary.end[:10]})")
    print(sep)
    print(
        f"Bars    : {summary.total_bars_scanned:<6}  "
        f"Signals: {summary.total_signals:<5}  "
        f"Trades: {summary.total_trades}"
    )
    print(
        f"Skipped (R:R): {summary.skipped_rr:<4}  "
        f"Skipped (entry timeout): {summary.skipped_entry}"
    )
    print(sep)
    n_completed = summary.wins + summary.losses
    if n_completed == 0:
        print("No completed trades.")
    else:
        wr_pct = round(summary.winrate * 100, 1)
        print(
            f"Wins : {summary.wins}   Losses : {summary.losses}   B/E : {summary.breakevens}"
        )
        print(f"Winrate : {wr_pct}%   PF: {summary.profit_factor}   Expectancy: {summary.expectancy:+.2f}R")
        print(
            f"Avg W: +{summary.avg_winner_r}R   Avg L: {summary.avg_loser_r}R   "
            f"MaxConsecL: {summary.max_consec_losses}"
        )
        print(
            f"Avg bars/trade: {summary.avg_bars_in_trade}   "
            f"Max: {summary.max_bars_in_trade}"
        )
        # Change 6: display monthly_pnl_pct prominently
        if summary.risk_pct != 1.0 or summary.monthly_pnl_pct != 0.0:
            print(
                f"Risk/trade: {summary.risk_pct}%   "
                f"Total PnL: {summary.total_pnl_pct:+.2f}%   "
                f"Monthly: {summary.monthly_pnl_pct:+.2f}%/mo"
            )

    if summary.session_breakdown:
        print(sep)
        print("Sessions:")
        for sess, stats in summary.session_breakdown.items():
            t = stats["trades"]
            w = stats["wins"]
            l = stats["losses"]
            wr = round(stats.get("winrate", 0) * 100, 1)
            print(f"  {sess:<14} {t:>3}T  {w}W/{l}L  {wr}%")

    if summary.total_trades > 0:
        print(sep)
        if summary.total_trades > 0:
            from copilot.journal.writer import default_journal_path
            print(
                f"{summary.total_trades} records written → journal "
                f"(record_type=backtest, run_id:{rid})"
            )
            print(f"Filter: trades --tag run_id:{rid}")
    print()


def write_summary_to_journal(
    summary: "BacktestSummary",  # noqa: F821
    trades: list[TradeRecord],
    path: Path | None = None,
) -> int:
    """
    Write all trade records to the journal (append_record for each).
    Returns count of records written.
    """
    count = 0
    for trade in trades:
        try:
            append_record(trade, path=path)
            count += 1
        except Exception as e:
            print(f"WARNING: failed to write record {trade.id[:8]}: {e}")
    return count


def print_walkforward(wf: "WalkForwardSummary") -> None:  # noqa: F821
    """Print in-sample and out-of-sample summaries side by side."""
    sep = "─" * 60
    print(f"\n{'═' * 60}")
    print(f"  WALK-FORWARD RESULTS  (split={wf.split_ratio:.0%}  bar #{wf.split_bar_index})")
    print(f"{'═' * 60}")
    print("\n  ── IN-SAMPLE ────────────────────────────────────────────")
    print_summary(wf.in_sample)
    print("\n  ── OUT-OF-SAMPLE ────────────────────────────────────────")
    print_summary(wf.out_of_sample)
    print(sep)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _max_consecutive_losses(pnl_series: list[float]) -> int:
    """Return the longest streak of negative pnl values."""
    max_streak = 0
    current = 0
    for pnl in pnl_series:
        if pnl < 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def _session_breakdown(trades: list[TradeRecord]) -> dict[str, dict]:
    """Group completed trades by session and compute per-session win stats."""
    breakdown: dict[str, dict] = {}
    for t in trades:
        sess = t.session or "unknown"
        if sess not in breakdown:
            breakdown[sess] = {"trades": 0, "wins": 0, "losses": 0, "be": 0, "pnl_r": []}
        breakdown[sess]["trades"] += 1
        if t.result in ("win",) or (t.result == "expired" and (t.pnl_r or 0.0) > 0.01):
            breakdown[sess]["wins"] += 1
        elif t.result in ("loss",) or (t.result == "expired" and (t.pnl_r or 0.0) < -0.01):
            breakdown[sess]["losses"] += 1
        elif t.result in ("be", "expired"):
            breakdown[sess]["be"] += 1
        if t.pnl_r is not None:
            breakdown[sess]["pnl_r"].append(t.pnl_r)

    for sess, stats in breakdown.items():
        n = stats["wins"] + stats["losses"]
        stats["winrate"] = round(stats["wins"] / n, 4) if n else 0.0

    return breakdown


def _estimate_months(start: str, end: str) -> float:
    """Estimate number of months between two ISO date strings."""
    try:
        from datetime import datetime, timezone
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        s = datetime.strptime(start[:19] + "Z", fmt).replace(tzinfo=timezone.utc)
        e = datetime.strptime(end[:19] + "Z", fmt).replace(tzinfo=timezone.utc)
        days = (e - s).days
        return max(days / 30.44, 1.0)  # at least 1 month to avoid inflated monthly
    except Exception:
        return 1.0
