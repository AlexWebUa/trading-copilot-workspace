#!/usr/bin/env python
r"""Markdown tables from the detector-combination runs (`research/runs/combo_*.json`).

    .venv\Scripts\python.exe scripts/report_combo.py            # every stage on disk
    .venv\Scripts\python.exe scripts/report_combo.py --stage 7
    .venv\Scripts\python.exe scripts/report_combo.py --stage oos

The tables in docs/SETUP_COMBOS.md are this script's output, pasted.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

_OUT = Path(__file__).resolve().parent.parent / "research" / "runs"
_ORDER = ("1", "2a", "2b", "3a", "3b", "4a", "4b", "5a", "5b", "6", "7", "8a", "8b")
_PREFIX = "combo"            # "combo_xau" for gold: --prefix


def _load(stage: str) -> list[dict]:
    path = _OUT / (f"{_PREFIX}_oos.json" if stage == "oos" else f"{_PREFIX}_stage{stage}.json")
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))["arms"]
    for r in rows:
        r["stage"] = stage
    return rows


def _ci(ci) -> str:
    return f"[{ci[0]:+.2f}, {ci[1]:+.2f}]"


def stage_table(rows: list[dict]) -> str:
    out = ["| Арма | n | в мес. | WR | E, R | Интервал 95% | Случайный вход, R | Сверх случайного | Интервал 95% | Стоп, ATR | Издержки, R | К случайному входу | К нулю |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        s = r["stats"]
        if not s["n"]:
            out.append(f"| `{r['name']}` | 0 | | | | | | | | | | нет сделок | нет сделок |")
            continue
        c = r["control"]
        out.append(
            f"| `{r['name']}` | {s['n']} | {s['per_month']} | {s['winrate']:.1%} | {s['mean_r']:+.3f} | "
            f"{_ci(s['mean_r_ci'])} | {c['net_r']:+.3f} | {s['excess_r']:+.3f} | {_ci(s['excess_r_ci'])} | "
            f"{s['median_risk_atr']:.2f} | {s['median_cost_r']:.2f} | "
            f"{r['verdict_control']} | {r['verdict']} |")
    return "\n".join(out)


def chain_table(rows: list[dict]) -> str:
    """Long and short pooled per chain and timeframe: the drift largely cancels."""
    cells: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        if r["stats"]["n"]:
            chain = r["name"].rsplit("_", 2)[0]
            cells.setdefault((chain, r["tf"]), []).append(r)
    out = ["| Цепочка | ТФ | n | Без издержек, лонг | шорт | вместе | С издержками, вместе | Сверх случайного, вместе |",
           "|---|---|---|---|---|---|---|---|"]
    for (chain, tf), arms in cells.items():
        n = sum(a["stats"]["n"] for a in arms)
        side = {a["side"]: a["stats"] for a in arms}
        pooled = lambda key: sum(a["stats"][key] * a["stats"]["n"] for a in arms) / n  # noqa: E731
        cell = lambda k: f"{side[k]['gross_r']:+.3f}" if k in side else "—"  # noqa: E731
        out.append(f"| {chain} | {tf} | {n} | {cell('long')} | {cell('short')} | {pooled('gross_r'):+.3f} | "
                   f"{pooled('mean_r'):+.3f} | {pooled('excess_r'):+.3f} |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage")
    ap.add_argument("--chains", action="store_true", help="the pooled chain x timeframe table")
    ap.add_argument("--prefix", default="combo", help="result file prefix: combo | combo_xau")
    args = ap.parse_args()
    global _PREFIX
    _PREFIX = args.prefix
    stages = [args.stage] if args.stage else list(_ORDER)
    every: list[dict] = []
    for stage in stages:
        rows = _load(stage)
        if not rows:
            continue
        every += rows
        print(f"\n### {'Отложенный год' if stage == 'oos' else 'Этап ' + stage}\n")
        print(stage_table(rows))
    print(f"\nВсего арм: {len(every)}.")
    print(f"К случайному входу: {dict(Counter(r['verdict_control'] for r in every))}")
    print(f"К нулю: {dict(Counter(r['verdict'] for r in every))}")
    if args.chains:
        print("\n### По цепочкам, лонг и шорт вместе\n")
        print(chain_table([r for r in every if "__" not in r["name"]]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
