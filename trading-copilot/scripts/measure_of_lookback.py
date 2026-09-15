#!/usr/bin/env python
"""At what warm-up does `detect_order_flow` stop depending on where it started?

Why this matters now. Stage 1 gave only three arms with >= 30 trades on a year
of 30m data; the POI arms need two to three years to be measurable at all. But
`lookback=0` makes the sweep quadratic — the detector re-walks the whole prefix
on every bar — so tripling the window costs about nine times the compute
(~18 min per arm becomes ~2.7 h). A bounded window turns that back into linear
time.

The earlier measurement (recorded in `rules_30mof.py`) tested 600 and 1000 bars.
Structure had already converged at 600; `pool_level` had NOT converged at 1000,
so the rules kept `lookback=0`. It never tested higher. If the pool converges at
some affordable window, multi-year runs become cheap; if it does not, they stay
quadratic and the answer is to buy the time rather than fake it.

Compares each bounded window against the unbounded walk on the same slices, and
reports agreement per field separately: direction/confirmed/keys are the
structure, `pool_level` and `entries_allowed` are the frequency gate.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from copilot.data.binance import BinanceSource          # noqa: E402
from copilot.detectors.order_flow import detect_order_flow  # noqa: E402

_WINDOWS = (1000, 2000, 3000, 4000, 6000, 8000)
_FIELDS = ("direction", "confirmed", "confirmations", "entries_allowed")


def _key_price(r: dict, side: str):
    k = r.get(side)
    return None if not k else k.get("price")


def _snapshot(r: dict) -> dict:
    return {
        **{f: r.get(f) for f in _FIELDS},
        "key_high": _key_price(r, "key_high"),
        "key_low": _key_price(r, "key_low"),
        "pool_level": r.get("pool_level"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=17520)
    ap.add_argument("--slices", type=int, default=120,
                    help="Evenly spaced evaluation points across the window")
    args = ap.parse_args()

    df = BinanceSource().get_ohlc("BTCUSDT", "30m", args.bars)
    print(f"{len(df)} bars, {df.index[0]} → {df.index[-1]}")

    # Only evaluate where the largest window has room, or the comparison is
    # between two truncated walks rather than against the full one.
    lo = max(_WINDOWS) + 50
    step = max(1, (len(df) - lo) // args.slices)
    points = list(range(lo, len(df), step))[: args.slices]
    print(f"{len(points)} slices from bar {points[0]} to {points[-1]}\n")

    full: list[dict] = []
    t0 = time.time()
    for i in points:
        full.append(_snapshot(detect_order_flow(df.iloc[: i + 1], swing_lookback=1, lookback=0)))
    print(f"unbounded reference: {time.time() - t0:.0f}s\n")

    rows = []
    fields = list(_FIELDS) + ["key_high", "key_low", "pool_level"]
    print(f"{'window':>7}  {'time':>6}  " + "  ".join(f"{f:>14}" for f in fields))
    for w in _WINDOWS:
        t0 = time.time()
        got = [
            _snapshot(detect_order_flow(df.iloc[: i + 1], swing_lookback=1, lookback=w))
            for i in points
        ]
        secs = time.time() - t0
        agree = {
            f: sum(1 for a, b in zip(full, got) if a[f] == b[f]) / len(points)
            for f in fields
        }
        rows.append({"window": w, "seconds": round(secs, 1), **agree})
        print(f"{w:>7}  {secs:>5.0f}s  " + "  ".join(f"{agree[f]:>13.0%}" for f in fields))

    out = Path(__file__).resolve().parent.parent / "research" / "runs" / "of_lookback.json"
    out.write_text(json.dumps({"bars": args.bars, "slices": len(points), "rows": rows},
                              indent=2), encoding="utf-8")
    print(f"\n-> {out}")
    print("A window is usable only if BOTH the structure fields and pool_level/"
          "entries_allowed hit 100%. The gate is part of the rule, not a detail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
