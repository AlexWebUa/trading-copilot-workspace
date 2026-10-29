#!/usr/bin/env python
r"""Download Dukascopy M1 history once, so an instrument can be backtested offline.

    .venv\Scripts\python.exe scripts/fetch_dukascopy.py --from-year 2015
    .venv\Scripts\python.exe scripts/fetch_dukascopy.py --from-year 2015 --build-only

Needs Node.js: the download itself is `npx dukascopy-node` (an npm package —
there is no pip package of that name). One CSV per year and price side goes to a
staging folder; a year already there is not fetched again, except the current
one. The staged files are then merged into two parquet frames in the project's
cache, read by `copilot.data.dukascopy.DukascopySource`.

Nothing lands in the repository: Dukascopy's data is free for personal use and
not ours to redistribute.

Bid and ask are both kept. The bid frame is the chart — the wicks a trader sees
on a spot gold feed; the ask frame exists so costs can use the spread that was
actually quoted on each bar instead of a constant.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from copilot.data.cache import BatchedOHLCStore  # noqa: E402
from copilot.data.dukascopy import SIDES, csv_to_frame, source_id  # noqa: E402


def staging_dir(instrument: str) -> Path:
    path = BatchedOHLCStore()._dir / "dukascopy" / instrument.lower()
    path.mkdir(parents=True, exist_ok=True)
    return path


def fetch_year(instrument: str, year: int, side: str, end: pd.Timestamp, stage: Path) -> Path:
    """One calendar year of M1 bars for one price side. `-to` is exclusive."""
    name = f"{instrument.lower()}_m1_{side}_{year}"
    target = stage / f"{name}.csv"
    year_end = pd.Timestamp(year=year + 1, month=1, day=1)
    complete = year_end <= end
    if target.exists() and target.stat().st_size > 0 and complete:
        return target
    npx = shutil.which("npx")
    if npx is None:
        raise RuntimeError("npx not found: install Node.js to download from Dukascopy")
    date_to = min(year_end, end).strftime("%Y-%m-%d")
    cmd = [npx, "--yes", "dukascopy-node", "-i", instrument.lower(),
           "-from", f"{year}-01-01", "-to", date_to, "-t", "m1", "-p", side,
           "-v", "-vu", "units", "-f", "csv", "-fn", name, "-dir", str(stage),
           "-bs", "50", "-bp", "500", "-r", "3", "-s"]
    t0 = time.time()
    done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    # No retry-on-empty: weekends and holidays are empty by nature, and with that
    # flag the tool gives up on the first Saturday.
    if done.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"dukascopy-node failed for {name}:\n{done.stdout[-800:]}\n{done.stderr[-800:]}")
    print(f"  {name}: {target.stat().st_size / 1e6:6.1f} MB за {time.time() - t0:5.0f} с", flush=True)
    return target


def build(instrument: str, stage: Path) -> None:
    """Merge the staged years into one frame per side and store them."""
    store = BatchedOHLCStore()
    symbol = instrument.upper()
    for side in SIDES:
        files = sorted(stage.glob(f"{instrument.lower()}_m1_{side}_*.csv"))
        if not files:
            raise RuntimeError(f"no staged {side} files in {stage}")
        df = pd.concat([csv_to_frame(f) for f in files]).sort_index()
        df = df[~df.index.duplicated(keep="last")]
        store.save(source_id(side), symbol, "1m", df, at_history_start=True)
        print(f"{symbol} {side}: {len(df):,} баров M1, {df.index[0]} .. {df.index[-1]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instrument", default="xauusd")
    ap.add_argument("--from-year", type=int, default=2015)
    ap.add_argument("--to", default=None, help="YYYY-MM-DD, exclusive; default: today")
    ap.add_argument("--build-only", action="store_true", help="skip the download, rebuild the parquet")
    args = ap.parse_args()

    stage = staging_dir(args.instrument)
    end = pd.Timestamp(args.to) if args.to else pd.Timestamp.now().normalize()
    if not args.build_only:
        print(f"{args.instrument.upper()} M1, {args.from_year} .. {end.date()} → {stage}")
        for year in range(args.from_year, end.year + 1):
            if pd.Timestamp(year=year, month=1, day=1) >= end:
                break
            for side in SIDES:
                fetch_year(args.instrument, year, side, end, stage)
    build(args.instrument, stage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
