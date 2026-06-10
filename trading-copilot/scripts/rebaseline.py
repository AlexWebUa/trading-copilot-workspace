"""
P0-7 re-baseline (June 2026): rerun every rule walk-forward with the
P0-1..P0-6 fixes in place. First trustworthy expectancy numbers.

Cost model: 4 bps taker fee + 2 bps slippage PER SIDE on every rule.
Journal writes disabled — the markdown report is the artifact; old journal
records predate the fixes and are not comparable.

Usage:  python scripts/rebaseline.py [--bars 2000] [--symbol BTCUSDT] [--tf 1h]
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from copilot.backtest.engine import BacktestEngine, WalkForwardSummary
from copilot.backtest.rules import BUILTIN_RULES
from copilot.backtest.rules_orderflow import ORDERFLOW_RULES

FEE_BPS = 4.0       # Binance USD-M taker, per side
SLIPPAGE_BPS = 2.0  # per side

# Rules whose conditions depend on detectors still quarantined/broken
# (June audit; rewrites scheduled P2). Run anyway, but flag in the report.
_TAINTED = {
    "sponsored_cd_ob_hvn_long": "check_cd_absorption (broken thresholds, P2)",
    "compression_vp_break_long": "detect_compression (noise, P2)",
    "ob_in_hvn_long": "check_ob_in_hvn untested at scale",
}


def _fmt(s) -> str:
    return (
        f"{s.total_trades:>3} trades | winrate {s.winrate:5.1%} | "
        f"expectancy {s.expectancy:+.3f}R | PF {s.profit_factor:5.2f} | "
        f"signals {s.total_signals}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=2000)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--split", type=float, default=0.7)
    args = ap.parse_args()

    all_rules = {**BUILTIN_RULES, **ORDERFLOW_RULES}
    engine = BacktestEngine()
    rows: list[dict] = []

    for name, rule in all_rules.items():
        rule = dataclasses.replace(rule, fee_bps=FEE_BPS, slippage_bps=SLIPPAGE_BPS)
        t0 = time.time()
        print(f"\n=== {name} ===", flush=True)
        try:
            result = engine.run(
                args.symbol, args.tf, rule,
                bars=args.bars,
                walkforward_split=args.split,
                write_journal=False,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {exc}")
            rows.append({"name": name, "error": str(exc)})
            continue

        assert isinstance(result, WalkForwardSummary)
        is_, oos = result.in_sample, result.out_of_sample
        print(f"  IS : {_fmt(is_)}")
        print(f"  OOS: {_fmt(oos)}")
        print(f"  ({time.time() - t0:.0f}s)")
        rows.append({"name": name, "is": is_, "oos": oos})

    # ── Markdown report ──────────────────────────────────────────────────
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# Re-baseline — {ts} (P0-7)",
        "",
        f"All rules, walk-forward {args.split:.0%}/{1-args.split:.0%} split, "
        f"{args.symbol} {args.tf}, {args.bars} bars.",
        f"Cost model: {FEE_BPS:.0f} bps fee + {SLIPPAGE_BPS:.0f} bps slippage per side, "
        "charged on entry and exit notional.",
        "",
        "These are the first numbers produced after the June 2026 fixes "
        "(P0-1 forming bar, P0-2 look-ahead, P0-3 detector rewrap, "
        "P0-5 CD rewrite, P0-6 cost model). "
        "**All earlier backtest results are invalid and not comparable.**",
        "",
        "| Rule | Split | Trades | Winrate | Expectancy (R) | PF | Signals | Note |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        note = _TAINTED.get(r["name"], "")
        if "error" in r:
            lines.append(f"| {r['name']} | — | — | — | — | — | — | ERROR: {r['error']} |")
            continue
        for split_name, s in (("IS", r["is"]), ("OOS", r["oos"])):
            lines.append(
                f"| {r['name']} | {split_name} | {s.total_trades} | "
                f"{s.winrate:.1%} | {s.expectancy:+.3f} | {s.profit_factor:.2f} | "
                f"{s.total_signals} | {note} |"
            )

    lines += [
        "",
        "Notes:",
        "- `Signals` counts condition hits; trades may be fewer "
        "(RR filter < 1.0, entry timeout, session filter).",
        "- 0 trades on a rule means its confluence never lined up in this window — "
        "an honest null result, not an error.",
        "- Tainted rules depend on detectors still scheduled for rewrite (P2); "
        "their numbers carry no evidential weight.",
    ]

    out = Path(__file__).resolve().parent.parent / f"REBASELINE_{ts}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {out}")


if __name__ == "__main__":
    main()
