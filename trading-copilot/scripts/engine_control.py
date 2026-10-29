#!/usr/bin/env python
r"""Measure `SetupRule` arms against a same-side random entry (RESEARCH_PROTOCOL §2.5).

    .venv\Scripts\python.exe scripts/engine_control.py --symbol XAUUSD --tf 3m \
        --files "research/runs/costs_recheck_xau_ctl_*.json" --tag xau_engine
    .venv\Scripts\python.exe scripts/engine_control.py --symbol XAUUSD --tf 30m \
        --files "research/runs/30mof_stage*_xau_*.json" --tag xau_30mof

The engine scores an arm against zero. In a trending window that flatters one
side: over 2023-09 → 2025-09 gold rose 1.91x and a random 1h long made about
+0.24R. This takes the trades a runner kept with `--dump-trades` and draws, for
each arm, random market entries of the same side with each trade's own risk and
reward-to-risk, the same exit rules and the same costs — the control
`scripts/run_combo.py` uses, on a frame of the arm's entry timeframe.

`--hours-ny A,B` also draws the entries only from bars opening in [A, B) New York:
for a session-timed setup that separates "the setup" from "that hour of the day".
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import run_combo as rc  # noqa: E402
from copilot.backtest.combo import ComboParams  # noqa: E402
from copilot.backtest.report import bootstrap_expectancy_ci  # noqa: E402

_OUT = Path(__file__).resolve().parent.parent / "research" / "runs"
_NY = "America/New_York"


def _trades(rows: list[dict]) -> pd.DataFrame:
    t = pd.DataFrame(rows)
    t = t.dropna(subset=["entry", "stop", "pnl_r"])
    risk = (t["entry"] - t["stop"]).abs()
    t = t[risk > 0].copy()
    risk = (t["entry"] - t["stop"]).abs()
    rr = (t["tp"] - t["entry"]).abs() / risk
    # A trade without a recorded target takes the arm's typical one.
    fallback = float(rr.median()) if rr.notna().any() else 2.0
    sign = np.where(t["direction"] == "long", 1.0, -1.0)
    t["tp"] = t["tp"].fillna(t["entry"] + sign * fallback * risk)
    t["risk_pct"] = risk / t["entry"] * 100.0
    t["closed"] = True
    t["r"] = t["pnl_r"].astype(float)
    return t


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--files", required=True, help="glob of runner JSONs written with --dump-trades")
    ap.add_argument("--symbol", default="XAUUSD", choices=sorted(rc.INSTRUMENTS))
    ap.add_argument("--tf", required=True, help="frame the random entries are drawn on: the entry timeframe")
    ap.add_argument("--start", default=str(rc._START.date()))
    ap.add_argument("--end", default=str(rc._SPLIT.date()))
    ap.add_argument("--fee-bps", type=float, default=0.4)
    ap.add_argument("--slippage-bps", type=float, default=0.2)
    ap.add_argument("--hours-ny", default=None, help="A,B: also a control drawn only from these New York hours")
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()

    rc._INSTR = rc.INSTRUMENTS[args.symbol]
    lo, hi = pd.Timestamp(args.start, tz="UTC"), pd.Timestamp(args.end, tz="UTC")
    df = rc.frame(args.tf)
    df = df[df.index < hi]                      # nothing past the window is ever drawn from
    allowed = None
    if args.hours_ny:
        a, b = (int(x) for x in args.hours_ny.split(","))
        hour = df.index.tz_convert(_NY).hour.to_numpy()
        allowed = (hour >= a) & (hour < b)

    out: dict = {"symbol": args.symbol, "tf": args.tf, "window": f"{lo.date()} .. {hi.date()}",
                 "cost_bps_per_side": args.fee_bps + args.slippage_bps, "hours_ny": args.hours_ny, "arms": {}}
    for path in sorted(glob.glob(args.files)):
        for name, row in json.loads(Path(path).read_text(encoding="utf-8"))["arms"].items():
            if not row.get("trade_list"):
                continue
            t = _trades(row["trade_list"])
            side = t["direction"].iloc[0]
            params = ComboParams(side=side, cost_bps=args.fee_bps + args.slippage_bps)
            arm = t["r"].to_numpy()
            res = {"n": int(len(t)), "side": side, "mean_r": round(float(arm.mean()), 3),
                   "mean_r_ci": list(bootstrap_expectancy_ci(arm.tolist())),
                   "median_risk_pct": round(float(t["risk_pct"].median()), 4)}
            for label, mask in (("control", None), ("control_same_hours", allowed)):
                if label == "control_same_hours" and mask is None:
                    continue
                summary, net = rc.random_control(df, t, params, lo, hi, allowed=mask)
                res[label] = {**summary, "excess_r": round(float(arm.mean() - net.mean()), 3),
                              "excess_r_ci": rc.excess_ci(arm, net)}
            res["excess_r"] = res["control"]["excess_r"]
            res["excess_r_ci"] = res["control"]["excess_r_ci"]
            res["verdict_control"] = rc._verdict_vs_control(res)
            out["arms"][name] = res
            same = res.get("control_same_hours")
            print(f"  {name:32} n={res['n']:4}  E {res['mean_r']:+.3f}R {res['mean_r_ci']}  |  случайный вход "
                  f"{res['control']['net_r']:+.3f}R  сверх него {res['excess_r']:+.3f}R {res['excess_r_ci']}"
                  + (f"  |  те же часы: {same['net_r']:+.3f}R, сверх {same['excess_r']:+.3f}R {same['excess_r_ci']}"
                     if same else "")
                  + f"  |  {res['verdict_control']}", flush=True)
    path = _OUT / f"engine_control_{args.tag}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
