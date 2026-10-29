#!/usr/bin/env python
"""Re-score a published arm with the cost model, changing nothing else.

`SetupRule.fee_bps` and `slippage_bps` default to 0.0 and no rule file sets
them, so every setup research run before 2026-08-27 scored free trades. This
re-runs a named arm on its published window with costs charged, so the delta is
the cost model and nothing else.

    --arms bellissimo_1h3m_long,bellissimo_1h3m_short --tf 1h --bars 5000
    --arms nyam_mkt_long --tf 1h --bars 5000
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from copilot.backtest.engine import BacktestEngine          # noqa: E402
from copilot.backtest.rules_bellissimo import BELLISSIMO_RULES  # noqa: E402
from copilot.backtest.rules import AnyOf                         # noqa: E402
from copilot.backtest.rules_silver_bullet import SILVER_BULLET_RULES  # noqa: E402
from copilot.data.sources import OFFLINE_SYMBOLS, source_for    # noqa: E402
from copilot.backtest.report import dump_trades                  # noqa: E402

_ALL = {**BELLISSIMO_RULES, **SILVER_BULLET_RULES}

_OUT = Path(__file__).resolve().parent.parent / "research" / "runs"


# Spot gold's day starts at 17:00 New York, which is midnight in Kyiv for all but
# the few weeks a year when the US and EU clocks change on different dates — and
# it is the day the trader's own chart draws. UTC midnight would cut each session
# in two, so on gold the previous-day levels are taken on Kyiv days.
_GOLD_DAY_TZ = "Europe/Kyiv"


def _with_day_tz(cond, tz: str):
    if isinstance(cond, AnyOf):
        return AnyOf([_with_day_tz(c, tz) for c in cond.conditions])
    if cond.detector == "detect_previous_day_levels":
        return dataclasses.replace(cond, kwargs={**cond.kwargs, "day_tz": tz})
    return cond


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--arms", default="bellissimo_1h3m_long,bellissimo_1h3m_short")
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--bars", type=int, default=5000)
    # Pin the published window: "the last N bars" moves with the clock, so a
    # re-run a month later would score different trades.
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--fee-bps", type=float, default=4.0)
    ap.add_argument("--slippage-bps", type=float, default=2.0)
    ap.add_argument("--tag", default="")
    ap.add_argument("--dump-trades", action="store_true",
                    help="keep each trade, for scripts/engine_control.py")
    args = ap.parse_args()

    _OUT.mkdir(parents=True, exist_ok=True)
    out_path = _OUT / f"costs_recheck{('_' + args.tag) if args.tag else ''}.json"
    out: dict = {"symbol": args.symbol, "bars": args.bars, "start": args.start, "end": args.end, "fee_bps": args.fee_bps,
                 "slippage_bps": args.slippage_bps, "arms": {}}

    offline = args.symbol.upper() in OFFLINE_SYMBOLS
    engine = BacktestEngine(source=source_for(args.symbol, args.end))
    for name in args.arms.split(","):
        name = name.strip()
        rule = dataclasses.replace(
            _ALL[name],
            fee_bps=args.fee_bps, slippage_bps=args.slippage_bps,
        )
        if offline:
            rule = dataclasses.replace(
                rule, conditions=[_with_day_tz(c, _GOLD_DAY_TZ) for c in rule.conditions])
        t0 = time.time()
        s = engine.run(args.symbol, args.tf, rule, bars=args.bars, start=args.start, end=args.end, write_journal=False)
        out["arms"][name] = {
            "signals": s.total_signals,
            "trades": s.total_trades, "wins": s.wins, "losses": s.losses,
            "winrate": s.winrate, "unfinished": s.unfinished,
            "expectancy": s.expectancy, "expectancy_ci": s.expectancy_ci,
            "profit_factor": s.profit_factor, "skipped_rr": s.skipped_rr,
            "start": s.start, "end": s.end, "seconds": round(time.time() - t0, 1),
        }
        if args.dump_trades:
            out["arms"][name]["trade_list"] = dump_trades(s.trades)
        out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        r = out["arms"][name]
        print(f"{name:32} сделок {r['trades']:3}  W/L {r['wins']:2}/{r['losses']:2}  "
              f"E {r['expectancy']:>7}R  CI {r['expectancy_ci']}  "
              f"PF {r['profit_factor']}  ({r['seconds']}s)")
    print(f"-> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
