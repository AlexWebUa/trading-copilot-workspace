#!/usr/bin/env python
r"""ORB Algo | Flux Charts — calibration against TradingView, then the real run.

    .venv\Scripts\python.exe scripts/run_orb.py calibrate
    .venv\Scripts\python.exe scripts/run_orb.py sweep
    .venv\Scripts\python.exe scripts/run_orb.py fractal

`calibrate` reproduces the trader's screenshot of 14 Sep 2026 (BTCUSDT.P, 5m,
default settings): Total Days 35, Wins 12, Losses 20, Winrate 37.5%, Average
Profit 0.02%, Total Profit 0.66%. Nothing downstream is trusted until the
faithful port prints that table — a port that cannot reproduce the source's own
numbers is measuring a different strategy.

`sweep` runs three years for both anchors (00:00 UTC and the New York open),
switching the script's flattering behaviours off one at a time so each one's
share of the published result is visible.

`fractal` is the trader's variant of 2026-09-15 on the New York anchor: stop
behind the last 3-candle fractal confirmed before the open (floored at 0.5 ATR),
optional order-flow bias on 1h or 4h, target 1.5R or the script's ATR ladder.
Six arms, selected on the first two years; the held-out year is read for the
selected cell only.
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

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from copilot.backtest.orb_algo import (  # noqa: E402
    OrbParams, OrbResult, bias_series, dashboard, simulate,
)
from copilot.backtest.report import bootstrap_expectancy_ci  # noqa: E402
from copilot.data.base import TF_MINUTES  # noqa: E402
from copilot.data.binance import BinanceSource, fetch_ohlcv_batched  # noqa: E402
from copilot.detectors.order_flow import detect_order_flow  # noqa: E402

_TV_SCREENSHOT = {
    "total_days": 35, "wins": 12, "losses": 20,
    "winrate_pct": 37.5, "avg_profit_pct": 0.02, "total_profit_pct": 0.66,
}
# Screenshot file stamped 21:00 Kyiv on 14 Sep 2026 = 18:00 UTC. TradingView had
# ~10000 5m bars loaded (34.7 days, consistent with "Total Days 35").
_TV_END = pd.Timestamp("2026-09-14 18:00", tz="UTC")
_KYIV = "Europe/Kyiv"

_START = pd.Timestamp("2023-09-14", tz="UTC")
_END = pd.Timestamp("2026-09-14", tz="UTC")
# Selection happens on the first two years; the last year is held out and read
# once, at the end, for whatever survives.
_SPLIT = pd.Timestamp("2025-09-14", tz="UTC")
_COST_BPS = 6.0          # 4 bps taker + 2 bps slippage, per side — the project's model
_OUT = Path(__file__).resolve().parent.parent / "research" / "runs"

_HONEST = {"fill_at_close": True, "stop_first": True, "skip_entry_bar": True}
_ABLATION = [
    ("как в TradingView", {}),
    ("+ тейк по close", {"fill_at_close": True}),
    ("+ стоп раньше тейка", {"fill_at_close": True, "stop_first": True}),
    ("+ без бара входа", dict(_HONEST)),
    ("+ издержки 4+2 bps", {**_HONEST, "cost_bps": _COST_BPS}),
]

_FRACTAL_TP = [
    ("1.5R", {"tp_method": "FixedR", "tp_r": 1.5}),
    ("ATR-лестница", {"tp_method": "ATR"}),
]


def calibrate() -> int:
    df = BinanceSource().get_ohlc("BTCUSDT", "5m", 12000)
    df = df[df.index < _TV_END]
    print(f"TradingView: {_TV_SCREENSHOT}\n")

    # TradingView's exact bar count is not on the screenshot, so scan a band
    # around 10000 and report every distinct table and which counts reproduce it.
    matches: list[int] = []
    last = None
    for n in range(9990, 10031):
        window = df.tail(n)
        d = dashboard(simulate(window, OrbParams()))
        if d == _TV_SCREENSHOT:
            matches.append(n)
        if d != last:
            tag = "  <- СОВПАЛО" if d == _TV_SCREENSHOT else ""
            print(f"{n:>5} баров с {window.index[0]}: {d}{tag}")
            last = d
    span = f"{matches[0]}..{matches[-1]}" if matches else "нет"
    print(f"\nсовпадение на {len(matches)} из 41 окон: {span}")

    n_best = matches[0] if matches else 10000
    res = simulate(df.tail(n_best), OrbParams())
    t = res.trades
    print("\nСделки 12-13 сентября (время Киев, как на графике):")
    for _, row in t[t["session"] >= pd.Timestamp("2026-09-12", tz="UTC")].iterrows():
        orb = res.orbs[int(row["orb_n"])]
        exit_ts = (res.index[orb.sl_i].tz_convert(_KYIV).strftime("%d.%m %H:%M")
                   if orb.sl_i not in (None, -1) else "—")
        print(f"  сессия {row['session'].tz_convert(_KYIV):%d.%m %H:%M}  "
              f"диапазон {row['range_high']:.1f}/{row['range_low']:.1f}  "
              f"{row['side']} {row['entry_ts'].tz_convert(_KYIV):%d.%m %H:%M} "
              f"@ {row['entry']:.1f}  SL {row['sl_init']:.1f}  "
              f"выход {row['exit_kind']} {exit_ts}  TP {row['tp_hits']}  "
              f"gross {row['gross_pct']:+.3f}%")
    return 0


def load_history(start: pd.Timestamp, end: pd.Timestamp, tf: str = "5m",
                 chunk: int = 90_000) -> pd.DataFrame:
    """Walk back in chunks under `fetch_ohlcv_batched`'s 100k-bar cap.

    Consecutive chunks share their edge bar, so the coverage store grows as one
    contiguous frame instead of being replaced by a disjoint window.
    """
    frames = []
    cursor = end
    while cursor > start:
        part = fetch_ohlcv_batched("BTCUSDT", tf, chunk,
                                   end_ms=int(cursor.value // 1_000_000))
        if part.empty or part.index[0] >= cursor:
            break
        frames.append(part)
        cursor = part.index[0]
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[(df.index >= start) & (df.index < end)]


def htf_bias(index: pd.DatetimeIndex, htf: str, warmup_days: int = 120) -> np.ndarray:
    """Order-flow direction on `htf` as of each 5m bar's close (+1 / -1 / 0).

    One pass of `detect_order_flow` over the whole HTF frame instead of a call
    per 5m bar: the walk is single-pass and causal, so its state after HTF bar k
    depends only on bars <= k, and the event list carries every flip with the
    candle that caused it. `bias_series` releases each flip only once that
    candle has closed. The warm-up exists because the trader's structure
    "нормализуется со временем" — a walk seeded on the first research day would
    start with no flow at all.
    """
    htf_min = TF_MINUTES[htf]
    start = index[0] - pd.Timedelta(days=warmup_days)
    bars = int((pd.Timestamp.now(tz="UTC") - start) / pd.Timedelta(minutes=htf_min)) + 10
    frame = BinanceSource().get_ohlc("BTCUSDT", htf, bars)
    if frame.index[0] > start:
        raise RuntimeError(f"{htf} history starts {frame.index[0]}, warm-up needs {start}")
    flow = detect_order_flow(frame, swing_lookback=1, max_events=10**9, lookback=0)
    events = list(reversed(flow.get("events", [])))       # detector returns newest first
    return bias_series(events, htf_min, index)


def _window(res: OrbResult, lo: pd.Timestamp, hi: pd.Timestamp) -> OrbResult:
    orbs = [o for o in res.orbs if lo <= res.index[o.start_i] < hi]
    t = res.trades
    return OrbResult(res.params, orbs, t[(t["session"] >= lo) & (t["session"] < hi)], res.index)


def _cut(res: OrbResult, lo: pd.Timestamp, hi: pd.Timestamp, weekdays: bool) -> pd.DataFrame:
    t = _window(res, lo, hi).trades
    return t[t["session"].dt.dayofweek < 5] if weekdays else t


def _stats(trades: pd.DataFrame) -> dict:
    t = trades[trades["closed"]].dropna(subset=["r"])
    if t.empty:
        return {"n": 0}
    r = t["r"]
    gain, loss = r[r > 0].sum(), -r[r < 0].sum()
    return {
        "n": int(len(t)),
        "winrate": round(float((t["net_pct"] > 0).mean()), 4),
        "mean_pct": round(float(t["net_pct"].mean()), 4),
        "mean_pct_ci": bootstrap_expectancy_ci(t["net_pct"].tolist()),
        "total_pct": round(float(t["net_pct"].sum()), 2),
        "mean_r": round(float(r.mean()), 3),
        "mean_r_ci": bootstrap_expectancy_ci(r.tolist()),
        "pf_r": round(float(gain / loss), 3) if loss > 0 else None,
        "median_risk_pct": round(float(t["risk_pct"].median()), 4),
    }


def _line(label: str, s: dict) -> str:
    if not s.get("n"):
        return f"  {label:24} нет сделок"
    return (f"  {label:24} n={s['n']:4}  WR {s['winrate']:.1%}  "
            f"E {s['mean_pct']:+.4f}% {s['mean_pct_ci']}  "
            f"итого {s['total_pct']:+.2f}%  |  E {s['mean_r']:+.3f}R {s['mean_r_ci']}  "
            f"PF {s['pf_r']}")


def sweep() -> int:
    df = load_history(_START - pd.Timedelta(days=1), _END)
    step = df.index.to_series().diff().dropna()
    gaps = int((step != pd.Timedelta(minutes=5)).sum())
    print(f"5m: {len(df)} баров, {df.index[0]} -> {df.index[-1]}, разрывов {gaps}\n")

    out: dict = {"start": str(_START), "end": str(_END), "split": str(_SPLIT),
                 "bars": len(df), "gaps": gaps, "anchors": {}}
    for anchor in ("utc0", "ny_open"):
        print(f"=== якорь {anchor}, диапазон 30m, остальное по умолчанию ===")
        rows = {}
        honest = None
        for label, flags in _ABLATION:
            res = simulate(df, OrbParams(anchor=anchor, **flags))
            full = _window(res, _START, _END)
            s = _stats(full.trades)
            if not flags:
                s["dashboard"] = dashboard(full)
                print(f"  дашборд TradingView за 3 года: {s['dashboard']}")
            print(_line(label, s))
            rows[label] = s
            honest = res

        t = _window(honest, _START, _END).trades
        closed = t[t["closed"]]
        cost_pct = 2 * _COST_BPS / 100
        extra = {
            "in_sample": _stats(_window(honest, _START, _SPLIT).trades),
            "held_out_last_year": _stats(_window(honest, _SPLIT, _END).trades),
            "long": _stats(t[t["side"] == "long"]),
            "short": _stats(t[t["side"] == "short"]),
            "risk_pct_quantiles": {str(q): round(float(closed["risk_pct"].quantile(q)), 4)
                                   for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
            "share_costs_exceed_1r": round(float((closed["risk_pct"] < cost_pct).mean()), 4),
        }
        if anchor == "ny_open":
            wd = t["session"].dt.dayofweek
            extra["weekdays"] = _stats(t[wd < 5])
            extra["weekends"] = _stats(t[wd >= 5])

        print("  честная версия, разрезы:")
        print(_line("2023-09..2025-09 (IS)", extra["in_sample"]))
        print(_line("последний год (OOS)", extra["held_out_last_year"]))
        print(_line("лонг", extra["long"]))
        print(_line("шорт", extra["short"]))
        if anchor == "ny_open":
            print(_line("будни", extra["weekdays"]))
            print(_line("выходные", extra["weekends"]))
        print(f"  риск до стопа, % цены: {extra['risk_pct_quantiles']}")
        print(f"  доля сделок, где издержки {cost_pct:.2f}% больше 1R: "
              f"{extra['share_costs_exceed_1r']:.1%}\n")
        out["anchors"][anchor] = {"ablation": rows, "honest": extra}

    _OUT.mkdir(parents=True, exist_ok=True)
    path = _OUT / "orb_3y.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"-> {path}")
    return 0


def fractal_sweep() -> int:
    df = load_history(_START - pd.Timedelta(days=1), _END)
    print(f"5m: {len(df)} баров, {df.index[0]} -> {df.index[-1]}\n")

    biases: dict = {"нет": None}
    for tf in ("1h", "4h"):
        b = htf_bias(df.index, tf)
        biases[tf] = b
        live = b[df.index >= _START]
        print(f"биас {tf}: бычий {np.mean(live == 1):.0%}, медвежий {np.mean(live == -1):.0%}, "
              f"нет {np.mean(live == 0):.0%}")
    print()

    base = {**_HONEST, "cost_bps": _COST_BPS, "anchor": "ny_open"}
    arms: dict[str, OrbResult] = {"эталон: центр + Dynamic": simulate(df, OrbParams(**base))}
    for bias_name, bias in biases.items():
        for tp_name, tp in _FRACTAL_TP:
            p = OrbParams(**base, sl_method="Fractal", min_stop_atr=0.5, **tp)
            arms[f"фрактал | {tp_name} | биас {bias_name}"] = simulate(df, p, bias=bias)

    print(f"=== первые два года (IS), якорь NY, издержки {_COST_BPS:g} bps/сторону ===")
    out: dict = {"start": str(_START), "end": str(_END), "split": str(_SPLIT), "arms": {}}
    cells = []
    for name, res in arms.items():
        row: dict = {}
        is_ref = name.startswith("эталон")
        for label, wd in (("все дни", False), ("будни", True)):
            s = _stats(_cut(res, _START, _SPLIT, wd))
            row[label] = s
            print(_line(f"{name} [{label}]", s))
            if not is_ref and s.get("n", 0) >= 30:
                cells.append((name, label, wd, s))
        closed = _cut(res, _START, _SPLIT, False)
        closed = closed[closed["closed"]]
        if not is_ref and not closed.empty:
            risk_px = (closed["entry"] - closed["sl_init"]).abs()
            floored = float(np.isclose(risk_px, 0.5 * closed["entry_atr"], rtol=1e-6).mean())
            row["risk_pct_median"] = round(float(closed["risk_pct"].median()), 4)
            row["share_floored"] = round(floored, 4)
            print(f"      риск до стопа, медиана {row['risk_pct_median']:.3f}% цены; "
                  f"стоп расширен до 0.5 ATR в {floored:.0%} сделок")
        out["arms"][name] = row
    print()

    if not cells:
        print("ни одна ячейка не набрала 30 сделок на IS")
    else:
        name, label, wd, s = max(cells, key=lambda c: c[3]["mean_r_ci"][0])
        print(f"сравнений: {len(cells)} ячеек. Лучшая по нижней границе на IS: "
              f"{name} [{label}]  E {s['mean_r']:+.3f}R {s['mean_r_ci']}")
        oos = _stats(_cut(arms[name], _SPLIT, _END, wd))
        print("отложенный последний год — только для неё:")
        print(_line(f"{name} [{label}] OOS", oos))
        out["selected"] = {"arm": name, "days": label, "comparisons": len(cells),
                           "in_sample": s, "held_out_last_year": oos}

    _OUT.mkdir(parents=True, exist_ok=True)
    path = _OUT / "orb_fractal_3y.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\n-> {path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("calibrate", "sweep", "fractal"))
    args = ap.parse_args()
    if args.command == "calibrate":
        return calibrate()
    if args.command == "sweep":
        return sweep()
    return fractal_sweep()


if __name__ == "__main__":
    raise SystemExit(main())
