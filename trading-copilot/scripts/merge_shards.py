#!/usr/bin/env python
"""Merge sharded 30mOF outputs into one file, ordered as the stage defines.

Sharding exists only to use the machine's cores; the result has to read as if
one sequential sweep produced it, or arms get compared across files by eye.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from copilot.backtest.rules_30mof import (  # noqa: E402
    STAGE1_RULES, STAGE1B_RULES, STAGE2_RULES,
)

_ORDER = {"1": STAGE1_RULES, "1b": STAGE1B_RULES, "2": STAGE2_RULES}
_RUNS = Path(__file__).resolve().parent.parent / "research" / "runs"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="1", choices=("1", "1b", "2"))
    # Explicit, not a glob: the cost-on and cost-off sweeps live side by side in
    # this directory, and a glob would merge them into one table where half the
    # arms were scored on free trades.
    ap.add_argument("--prefix", default="",
                    help="Shard tag prefix, e.g. 'cost_' — must match the run's --tag")
    ap.add_argument("--by-side", action="store_true",
                    help="Shards were split per side too, i.e. tag <prefix><model>_<side>")
    args = ap.parse_args()

    models = sorted({n.replace("of30_", "").rsplit("_", 1)[0].removesuffix("_rr")
                     for n in _ORDER[args.stage]})
    if args.by_side:
        names = [f"{args.prefix}{m}_{d}" for m in models for d in ("long", "short")]
    else:
        names = [f"{args.prefix}{m}" for m in models]
    shards = [_RUNS / f"30mof_stage{args.stage}_{n}.json" for n in names]
    absent = [p.name for p in shards if not p.exists()]
    shards = [p for p in shards if p.exists()]
    if absent:
        print(f"WARNING: {len(absent)} shard file(s) absent: {', '.join(absent)}")
    if not shards:
        print(f"no shards for stage {args.stage} with prefix {args.prefix!r}")
        return 1

    merged: dict = {}
    arms: dict = {}
    for p in shards:
        d = json.loads(p.read_text(encoding="utf-8"))
        merged = {k: v for k, v in d.items() if k != "arms"}
        arms.update(d["arms"])

    # Windows are only comparable if every shard scored the same bars.
    windows = {(a.get("start"), a.get("end")) for a in arms.values() if "start" in a}
    if len(windows) > 1:
        print(f"WARNING: shards scored {len(windows)} different windows: {windows}")

    ordered = {n: arms[n] for n in _ORDER[args.stage] if n in arms}
    missing = [n for n in _ORDER[args.stage] if n not in arms]
    merged["arms"] = ordered
    if missing:
        merged["missing_arms"] = missing
        print(f"WARNING: {len(missing)} arm(s) absent: {', '.join(missing)}")

    out = _RUNS / f"30mof_stage{args.stage}_{args.prefix}merged.json"
    out.write_text(json.dumps(merged, indent=2, default=str), encoding="utf-8")
    print(f"{len(ordered)} arms from {len(shards)} shards -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
