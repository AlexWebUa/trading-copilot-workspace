#!/usr/bin/env python
r"""XAUUSD (Dukascopy) — what the data is, before any strategy is run on it.

    .venv\Scripts\python.exe scripts/measure_xau.py calendar   # coverage and closures
    .venv\Scripts\python.exe scripts/measure_xau.py verify     # resample vs Dukascopy's own bars
    .venv\Scripts\python.exe scripts/measure_xau.py costs      # ATR, spread, cost in R

`costs` is the table that decided 3m and 5m for BTC: how large a stop behind a
sweep wick is on each timeframe, and what share of it the round trip costs. Here
the cost is the spread Dukascopy quoted on the entry bar — one spread per round
trip, since a long buys at the ask and sells at the bid. Commission, slippage
and overnight swap are NOT in it; they depend on the trader's own broker.

Stops and trade counts come from the trader's example chain (A1) on the first two
years of the research window only. No result is read: `cost_bps=0` and only the
size of the stop is used, so the held-out year stays unopened for gold too.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from copilot.backtest.combo import ComboParams, simulate, sweep_bars  # noqa: E402
from copilot.data.dukascopy import DukascopySource, csv_to_frame, resample  # noqa: E402
from copilot.detectors.smc_lib import true_range_atr  # noqa: E402

_SYMBOL = "XAUUSD"
# The BTC research window, so the two instruments read the same years.
_START = pd.Timestamp("2023-09-14", tz="UTC")
_SPLIT = pd.Timestamp("2025-09-14", tz="UTC")
_WARMUP = pd.Timestamp("2023-04-13", tz="UTC")
_IS_MONTHS = 24.0
_NY = "America/New_York"
_OUT = Path(__file__).resolve().parent.parent / "research" / "runs"
TFS = ("3m", "5m", "15m", "30m", "1h")


def calendar() -> int:
    """Coverage, and every stretch without bars sorted into what it is."""
    m1 = DukascopySource().history(_SYMBOL, "1m")
    print(f"{_SYMBOL} M1 bid: {len(m1):,} баров, {m1.index[0]} .. {m1.index[-1]}")
    gap = m1.index.to_series().diff().dropna()
    gap = gap[gap > pd.Timedelta(minutes=1)]
    before = (gap.index - gap).dt.tz_convert(_NY)       # last bar before the gap, New York
    hours = gap / pd.Timedelta(hours=1)
    weekend = hours >= 40
    daily = (~weekend) & (hours >= 0.9) & (hours <= 1.2) & (before.dt.hour == 16)
    short = (~weekend) & (~daily) & (gap <= pd.Timedelta(minutes=10))
    other = ~(weekend | daily | short)
    print(f"  выходные: {int(weekend.sum())}   дневной перерыв 17:00–18:00 NY: {int(daily.sum())}   "
          f"минуты без тиков (до 10 мин): {int(short.sum())}   прочее: {int(other.sum())}")
    by_year = gap[other].groupby(gap[other].index.year).agg(["count", "sum"])
    print("  прочее по годам (число, суммарно часов):",
          {int(y): (int(r["count"]), round(r["sum"] / pd.Timedelta(hours=1))) for y, r in by_year.iterrows()})
    print("  последние 12 «прочих» закрытий (последний бар до → первый бар после, UTC):")
    for ts, g in gap[other].tail(12).items():
        print(f"    {ts - g:%Y-%m-%d %a %H:%M} → {ts:%Y-%m-%d %a %H:%M}   {g / pd.Timedelta(hours=1):5.1f} ч")
    for tf in TFS:
        df = resample(m1[(m1.index >= _WARMUP)], tf)
        print(f"  {tf:>3}: {len(df):,} баров с {_WARMUP.date()}")
    return 0


def verify(month: str) -> int:
    """Download Dukascopy's own m5 and h1 bars for one month and compare them,
    bar for bar, with the resample of the stored minutes."""
    npx = shutil.which("npx")
    if npx is None:
        raise SystemExit("npx not found")
    start = pd.Timestamp(month + "-01", tz="UTC")
    end = start + pd.offsets.MonthBegin(1)
    m1 = DukascopySource().history(_SYMBOL, "1m", start, end)
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        for native, tf in (("m5", "5m"), ("h1", "1h")):
            subprocess.run([npx, "--yes", "dukascopy-node", "-i", _SYMBOL.lower(),
                            "-from", f"{start:%Y-%m-%d}", "-to", f"{end:%Y-%m-%d}", "-t", native,
                            "-p", "bid", "-v", "-vu", "units", "-f", "csv", "-fn", native,
                            "-dir", tmp, "-s"], check=True, capture_output=True)
            ref = csv_to_frame(Path(tmp) / f"{native}.csv")
            mine = resample(m1, tf)
            both = mine.index.intersection(ref.index)
            cols = ["open", "high", "low", "close"]
            bad = int(((mine.loc[both, cols] - ref.loc[both, cols]).abs() > 1e-6).any(axis=1).sum())
            only_mine, only_ref = len(mine.index.difference(ref.index)), len(ref.index.difference(mine.index))
            print(f"{tf}: баров у нас {len(mine)}, у Dukascopy {len(ref)}, общих {len(both)}, "
                  f"расхождений в ценах {bad}, только у нас {only_mine}, только у них {only_ref}")
            ok &= bad == 0 and only_mine == 0 and only_ref == 0
    print("ресемпл совпадает" if ok else "ЕСТЬ РАСХОЖДЕНИЯ")
    return 0 if ok else 1


def _spread_bps(bid: pd.DataFrame, ask: pd.DataFrame) -> pd.Series:
    ask_close = ask["close"].reindex(bid.index).ffill()
    return (ask_close - bid["close"]) / bid["close"] * 10_000


def costs() -> int:
    src = DukascopySource()
    rows = []
    hourly = None
    for tf in TFS:
        bid = src.history(_SYMBOL, tf, _WARMUP, _SPLIT)
        ask = src.history(_SYMBOL, tf, _WARMUP, _SPLIT, side="ask")
        spread = _spread_bps(bid, ask)
        window = bid.index >= _START
        atr_pct = pd.Series(true_range_atr(bid), index=bid.index) / bid["close"] * 100
        trades, sweeps = [], 0
        for side in ("long", "short"):
            params = ComboParams(side=side, cost_bps=0.0)
            sw = sweep_bars(bid, params)
            sweeps += int((bid.index[sw] >= _START).sum())
            t = simulate(bid, params).trades
            trades.append(t[(t["known_ts"] >= _START) & t["closed"]])
        t = pd.concat(trades)
        entry_spread = spread.reindex(t["entry_ts"]).to_numpy()
        cost_r = entry_spread / (t["risk_pct"].to_numpy() * 100.0)
        rows.append({
            "tf": tf,
            "bars": int(window.sum()),
            "atr_pct": round(float(atr_pct[window].median()), 4),
            "spread_bps": round(float(spread[window].median()), 2),
            "spread_bps_p95": round(float(spread[window].quantile(0.95)), 2),
            "sweeps_per_month": round(sweeps / _IS_MONTHS, 1),
            "trades_per_month": round(len(t) / _IS_MONTHS, 1),
            "stop_pct": round(float(t["risk_pct"].median()), 4),
            "stop_atr": round(float(t["risk_atr"].median()), 2),
            "spread_cost_r": round(float(np.median(cost_r)), 3),
            "spread_cost_r_p90": round(float(np.quantile(cost_r, 0.9)), 3),
        })
        if tf == "5m":
            hour = bid.index[window].tz_convert(_NY).hour
            hourly = spread[window].groupby(hour).median().round(2)

    print(f"{_SYMBOL}, {_START.date()} .. {_SPLIT.date()} (первые два года окна), цены bid, спред Dukascopy")
    print("ТФ  | медианный ATR | спред, bps (медиана / p95) | свипов фрактала-5 в мес. | сделок A1 в мес. | "
          "стоп A1 (% / ATR) | спред в R (медиана / p90)")
    for r in rows:
        print(f"{r['tf']:>3} | {r['atr_pct']:.3f}%      | {r['spread_bps']:.2f} / {r['spread_bps_p95']:.2f}"
              f"               | {r['sweeps_per_month']:8.0f}                 | {r['trades_per_month']:6.1f}"
              f"           | {r['stop_pct']:.3f}% / {r['stop_atr']:.2f}   | {r['spread_cost_r']:.3f} / {r['spread_cost_r_p90']:.3f}")
    print("\nМедианный спред по часам Нью-Йорка (5m), bps:")
    print("  " + "  ".join(f"{h:02d}: {v:.2f}" for h, v in hourly.items()))
    price = src.history(_SYMBOL, "1h", _START, _SPLIT)
    drift = float(price["close"].iloc[-1] / price["open"].iloc[0])
    print(f"\nЦена за окно: {price['open'].iloc[0]:.0f} → {price['close'].iloc[-1]:.0f} (×{drift:.2f})")
    _OUT.mkdir(parents=True, exist_ok=True)
    out = {"symbol": _SYMBOL, "window": f"{_START.date()} .. {_SPLIT.date()}", "price_side": "bid",
           "drift": round(drift, 3), "timeframes": rows,
           "spread_bps_by_ny_hour": {int(h): float(v) for h, v in hourly.items()}}
    path = _OUT / "xau_measure.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("calendar")
    v = sub.add_parser("verify")
    v.add_argument("--month", default="2026-08", help="YYYY-MM")
    sub.add_parser("costs")
    args = ap.parse_args()
    if args.cmd == "calendar":
        return calendar()
    if args.cmd == "verify":
        return verify(args.month)
    return costs()


if __name__ == "__main__":
    sys.exit(main())
