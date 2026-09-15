"""Measure what the R-12 fix does to the Bellissimo numbers.

Runs both strict arms on the прогон-3 window twice: once as the engine behaves
now (HTF frame cut at the fill), once emulating the pre-fix behaviour. The
emulation reconstructs `df.iloc[:i+1]` exactly — `i` is the first HTF bar whose
OPEN is at or after the entry LTF bar — so the only difference between the two
runs is the defect itself.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

import copilot.backtest.engine as eng
from copilot.backtest.engine import BacktestEngine
from copilot.backtest.rules_bellissimo import BELLISSIMO_RULES

BARS = 5000
ARMS = ["bellissimo_1h3m_long", "bellissimo_1h3m_short"]
_FIXED = eng._htf_slice_asof


def _prefix_slice(df, htf_minutes, asof_ts):
    """What the resolver used to get: bars up to the loop's current HTF bar."""
    ltf_ts = asof_ts - pd.Timedelta(minutes=3)
    later = df.index[df.index >= ltf_ts]
    cutoff = later[0] if len(later) else df.index[-1]
    return df[df.index <= cutoff]


def _row(s) -> dict:
    return {
        "signals": s.total_signals,
        "trades": s.total_trades,
        "skipped_rr": s.skipped_rr,
        "skipped_entry": s.skipped_entry,
        "wins": s.wins,
        "losses": s.losses,
        "unfinished": s.unfinished,
        "winrate": s.winrate,
        "winrate_ci": s.winrate_ci,
        "expectancy": s.expectancy,
        "expectancy_ci": s.expectancy_ci,
        "profit_factor": s.profit_factor,
        "start": s.start,
        "end": s.end,
    }


def main() -> None:
    out: dict = {"bars": BARS, "arms": {}}
    for arm in ARMS:
        out["arms"][arm] = {}
        for label, impl in (("fixed", _FIXED), ("prefix", _prefix_slice)):
            eng._htf_slice_asof = impl
            print(f"[{arm}] {label} …", flush=True)
            summary = BacktestEngine().run(
                "BTCUSDT", "1h", BELLISSIMO_RULES[arm], bars=BARS, write_journal=False
            )
            out["arms"][arm][label] = _row(summary)
            print(f"    {json.dumps(out['arms'][arm][label])}", flush=True)
            Path("research/runs/r12_impact.json").write_text(
                json.dumps(out, indent=2), encoding="utf-8"
            )
    eng._htf_slice_asof = _FIXED
    print("\ndone -> research/runs/r12_impact.json")


if __name__ == "__main__":
    sys.exit(main())
