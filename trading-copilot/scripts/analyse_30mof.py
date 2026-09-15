#!/usr/bin/env python
"""Read merged 30mOF results and answer the two questions the sweep was for.

    .venv\\Scripts\\python.exe scripts/analyse_30mof.py --prefix cost_

Ranking is by the LOWER BOUND of the bootstrap interval, never the point
estimate. On this project the point estimate has claimed an edge three times
that later turned out to be an artefact, so the point estimate is printed but
does not order anything.

Two tables, because the sweep asks two different questions and they need
different discipline:

  1. WHICH POI  — seven entry models compared against each other. These are
     genuinely separate candidates, so the multiple-comparison count is seven
     and a single arm clearing the bar means little on its own.

  2. TOUCH vs FULL FILL — the same POI's two arms, paired. Both trade the same
     signals and differ only in fill price, so the question is directional
     ("does waiting for the far edge help THIS poi") and asked four times, not
     twelve. A pair is only readable when both halves have a real sample.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

_RUNS = Path(__file__).resolve().parent.parent / "research" / "runs"
_MIN_TRADES = 30

# The touch arm and the full-fill arm of the same POI.
_PAIRS = [
    ("fvg", "fvg", "fvg_full"),
    ("poi", "poi", "poi_full"),
    ("bpr", "bpr", "bpr_full"),
    ("ob", "ob", "ob_full"),
    ("stb", "stb", "stb_full"),
]


def _load(prefix: str) -> dict:
    arms: dict = {}
    meta: dict = {}
    for stage in ("1", "1b"):
        p = _RUNS / f"30mof_stage{stage}_{prefix}merged.json"
        if not p.exists():
            print(f"(нет {p.name} — пропускаю этап {stage})")
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        arms.update(d.get("arms", {}))
        meta = {k: v for k, v in d.items() if k != "arms"}
    return {"arms": arms, "meta": meta}


def _lo(a: dict) -> float:
    ci = a.get("expectancy_ci") or (0.0, 0.0)
    return float(ci[0])


def _fmt(name: str, a: dict) -> str:
    ci = a.get("expectancy_ci") or (None, None)
    n = a.get("trades", 0)
    flag = "  " if n >= _MIN_TRADES else " !"
    return (
        f"{flag}{name:24} n={n:4}  W/L {a.get('wins',0):3}/{a.get('losses',0):3}  "
        f"E {a.get('expectancy'):>8}R  CI [{ci[0]:>7}, {ci[1]:>7}]  "
        f"PF {a.get('profit_factor')}"
    )


def _model_of(arm: str) -> str:
    return arm.replace("of30_", "").rsplit("_", 1)[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="", help="e.g. 'cost_'")
    args = ap.parse_args()

    data = _load(args.prefix)
    arms = data["arms"]
    if not arms:
        print("нет данных")
        return 1

    m = data["meta"]
    costs = (
        f"{m.get('fee_bps', 0)}+{m.get('slippage_bps', 0)} bps/сторону"
        if m.get("fee_bps") is not None else "издержки НЕ УЧТЕНЫ"
    )
    print(f"\n{m.get('symbol')} {m.get('tf')}  {m.get('start')} → {m.get('end')}  |  {costs}")
    print(f"! = меньше {_MIN_TRADES} сделок, арма не оценивается (RESEARCH_PROTOCOL)\n")

    print("=" * 78)
    print("1. КАКАЯ POI — ранжирование по нижней границе интервала")
    print("=" * 78)
    for name in sorted(arms, key=lambda n: -_lo(arms[n])):
        print(_fmt(name, arms[name]))

    judged = [n for n, a in arms.items() if a.get("trades", 0) >= _MIN_TRADES]
    survivors = [n for n in judged if _lo(arms[n]) > 0]
    print(f"\nОценено арм: {len(judged)} из {len(arms)}.  "
          f"Нижняя граница > 0: {len(survivors) or '—'}"
          + (f" ({', '.join(survivors)})" if survivors else ""))
    if survivors:
        print(f"При {len(judged)} проверках одно-два ложных срабатывания ожидаемы "
              "при нулевом истинном эффекте. Выживших нести в этап 2.")

    print()
    print("=" * 78)
    print("2. КАСАНИЕ vs ФУЛЛФИЛЛ — парно, внутри одной POI")
    print("=" * 78)
    for label, touch, full in _PAIRS:
        for side in ("long", "short"):
            t = arms.get(f"of30_{touch}_{side}")
            f = arms.get(f"of30_{full}_{side}")
            if not t or not f:
                continue
            tn, fn = t.get("trades", 0), f.get("trades", 0)
            if tn < _MIN_TRADES or fn < _MIN_TRADES:
                print(f"  {label:4} {side:5}  выборки не хватает "
                      f"(касание n={tn}, фуллфилл n={fn}) — пара не читается")
                continue
            delta = round(f.get("expectancy", 0) - t.get("expectancy", 0), 3)
            better = "фуллфилл" if delta > 0 else "касание"
            print(f"  {label:4} {side:5}  касание E {t.get('expectancy'):>7}R (n={tn:3})  "
                  f"фуллфилл E {f.get('expectancy'):>7}R (n={fn:3})  "
                  f"Δ {delta:+.3f}R → {better}")
            print(f"        частота: фуллфилл берёт {fn}/{tn} = "
                  f"{fn / tn:.0%} сделок касания")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
