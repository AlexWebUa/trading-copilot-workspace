#!/usr/bin/env python
"""Distribution of stop distances per arm.

The cost-on/cost-off delta implied POI arms were trading $26-95 stops on BTC.
That was inference from `cost_r = (entry + exit) * bps / risk`; this measures
the risk distance directly off the trade records, no journal write needed —
`BacktestSummary.trades` already carries them.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dataclasses  # noqa: E402
from copilot.backtest.engine import BacktestEngine  # noqa: E402
from copilot.backtest.rules_30mof import STAGE1_RULES, STAGE1B_RULES  # noqa: E402

ALL = {**STAGE1_RULES, **STAGE1B_RULES}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="of30_market_long,of30_poi_short,of30_ob_short")
    ap.add_argument("--start", default="2025-08-27T12:00:00Z")
    ap.add_argument("--end", default="2026-08-27T00:00:00Z")
    args = ap.parse_args()

    engine = BacktestEngine()
    print(f"{'arm':24} {'n':>4} {'min':>8} {'p25':>8} {'median':>8} {'max':>9}  доля <$150")
    for name in args.arms.split(","):
        rule = dataclasses.replace(ALL[name.strip()], fee_bps=4.0, slippage_bps=2.0)
        s = engine.run("BTCUSDT", "30m", rule, bars=17520,
                       start=args.start, end=args.end, write_journal=False)
        risks = sorted(
            abs(t.entry_price - t.sl_price)
            for t in s.trades
            if t.entry_price and t.sl_price and t.pnl_r is not None
        )
        if not risks:
            print(f"{name:24} {'—':>4}")
            continue
        tiny = sum(1 for r in risks if r < 150) / len(risks)
        print(f"{name:24} {len(risks):>4} {risks[0]:>8.1f} "
              f"{risks[len(risks)//4]:>8.1f} {statistics.median(risks):>8.1f} "
              f"{risks[-1]:>9.1f}  {tiny:>7.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
