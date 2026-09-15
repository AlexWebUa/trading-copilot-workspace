#!/usr/bin/env python
"""
30mOF stage-1 run — 7 entry models x 2 sides, target fixed to `nearest_fractal`.

    .venv\\Scripts\\python.exe scripts/run_30mof.py                 # default: 1 year
    .venv\\Scripts\\python.exe scripts/run_30mof.py --bars 35000    # ~2 years
    .venv\\Scripts\\python.exe scripts/run_30mof.py --stage 2 --only market,poi

Writes `research/runs/30mof_stage<N>.json` after EVERY arm, so a run that dies
half way still leaves the arms it finished. The Linux session lost a set of raw
results to /tmp; this writes into the project tree on purpose
(`docs/WINDOWS_SETUP.md` §5).

Why stage 1 and stage 2 are separate commands: 7 entry models x 2 target
policies x 2 sides is 28 comparisons on one instrument. Silver Bullet's twelve
arms already produced exactly one borderline "edge" that had to be discarded on
multiple-comparison grounds. Stage 2 runs only the entry models that survived
stage 1, which makes it a semi-independent confirmation instead of another
lottery ticket. Fixed with the trader 2026-08-26.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from copilot.backtest.engine import BacktestEngine          # noqa: E402
from copilot.backtest.rules_30mof import (  # noqa: E402
    _ENTRY_MODELS, _ENTRY_MODELS_FULLFILL, _FRACTAL_3,
    STAGE1_RULES, STAGE1B_RULES, STAGE2_RULES,
)

_STAGES = {
    "1":  (STAGE1_RULES,  _ENTRY_MODELS,          ""),
    "1b": (STAGE1B_RULES, _ENTRY_MODELS_FULLFILL, ""),
    "2":  (STAGE2_RULES,  _ENTRY_MODELS,          "_rr"),
}

_OUT_DIR = Path(__file__).resolve().parent.parent / "research" / "runs"

# RESEARCH_PROTOCOL.md: an arm is not judged below this sample size.
_MIN_TRADES = 30

# The honest cost model of P0-6, same figures `scripts/rebaseline.py` uses:
# Binance USD-M taker 4 bps + 2 bps slippage, PER SIDE, charged on entry and
# exit notional. `SetupRule` defaults both to 0.0 and no setup rule file sets
# them, so a run that does not pass these is scoring free trades.
#
# It is not a rounding detail here. `_finalize_trade` charges
# (entry + exit) * bps / risk_distance, so the cost in R scales INVERSELY with
# the stop. `sl_logic="of_key"` pins the stop to a structural level, so a fill
# deep inside a POI can leave a ~0.1 ATR stop — and at BTC 64k a $20 stop pays
# about 3.8R per round trip. Full-fill arms are exactly where that happens.
_FEE_BPS = 4.0
_SLIPPAGE_BPS = 2.0


def _row(s) -> dict:
    return {
        "symbol": s.symbol,
        "tf": s.tf,
        "start": s.start,
        "end": s.end,
        "signals": s.total_signals,
        "trades": s.total_trades,
        "skipped_rr": s.skipped_rr,
        "skipped_entry": s.skipped_entry,
        "unfinished": s.unfinished,
        "wins": s.wins,
        "losses": s.losses,
        "winrate": s.winrate,
        "winrate_ci": s.winrate_ci,
        "expectancy": s.expectancy,
        "expectancy_ci": s.expectancy_ci,
        "profit_factor": s.profit_factor,
        "avg_bars_in_trade": s.avg_bars_in_trade,
        "max_consec_losses": s.max_consec_losses,
        "total_pnl_pct": s.total_pnl_pct,
    }


def _verdict(row: dict) -> str:
    """The interval, not the point estimate — a habit this project paid for."""
    ci = row.get("expectancy_ci")
    if not ci or row["trades"] == 0:
        return "нет сделок"
    # `bootstrap_expectancy_ci` collapses to a point at n=1, which reads as a
    # spectacular edge. RESEARCH_PROTOCOL.md §"отсев" needs >= 30 trades before
    # an arm is judged at all; below that the interval is decoration.
    if row["trades"] < _MIN_TRADES:
        return f"мало сделок (n={row['trades']})"
    lo, hi = ci
    if lo > 0:
        return "ЭДЖ"
    if hi < 0:
        return "отрицательный"
    return "неотличимо от нуля"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bars", type=int, default=17520, help="30m bars (17520 = 1 year)")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--tf", default="30m")
    ap.add_argument("--stage", default="1", choices=("1", "1b", "2"),
                    help="1 = seven entry models on touch; 1b = the full-fill "
                         "half of the POI pairs; 2 = flat 1.8R target")
    ap.add_argument("--only", default=None,
                    help="Comma-separated entry models, e.g. market,poi,stb")
    ap.add_argument("--side", default="both", choices=("long", "short", "both"),
                    help="Shard a single entry model across two processes")
    ap.add_argument("--journal", action="store_true",
                    help="Write trades to the journal (off by default: a sweep would flood it)")
    # Pinning the window matters once arms run in parallel or over hours: the
    # default path asks for "the most recent N bars", so arm 1 and arm 14 of a
    # 2.8 h sweep are scored on windows that differ by five bars. Pass both and
    # every arm sees byte-identical data.
    ap.add_argument("--start", default=None, help="ISO window start, e.g. 2025-08-27T12:00:00Z")
    ap.add_argument("--end", default=None, help="ISO window end")
    ap.add_argument("--of-lookback", type=int, default=None,
                    help="Override detect_order_flow lookback. 0 = full history "
                         "(what run 1 used); 8000 reproduces it exactly on the "
                         "research year and makes the sweep linear "
                         "(research/runs/of_lookback.json)")
    ap.add_argument("--min-stop-atr", type=float, default=None,
                    help="Override the minimum stop. Pass 0 to reproduce a "
                         "pre-2026-08-27 run, which had no floor.")
    ap.add_argument("--fee-bps", type=float, default=_FEE_BPS,
                    help="Taker fee per side, bps (0 = the old free-trade run)")
    ap.add_argument("--slippage-bps", type=float, default=_SLIPPAGE_BPS,
                    help="Slippage per side, bps")
    ap.add_argument("--tag", default="",
                    help="Suffix for the output file. Parallel shards MUST each "
                         "pass their own, or they overwrite one another.")
    args = ap.parse_args()

    if args.of_lookback is not None:
        # Every condition in every arm shares this one dict by reference, so
        # mutating it here is the whole override. Deliberate: the alternative
        # is rebuilding 22 rules' condition lists to change one number.
        _FRACTAL_3["lookback"] = args.of_lookback

    rules, models, suffix = _STAGES[args.stage]
    if args.side != "both" and not args.only:
        print("--side needs --only: sharding by side only makes sense per model.")
        return 1
    if args.only:
        wanted = {m.strip() for m in args.only.split(",") if m.strip()}
        # Exact model match, not a prefix test: `--only fvg` used to drag
        # `of30_fvg_full_*` along with it, which silently doubled a shard and
        # ran the same arm in two processes.
        sides = ("long", "short") if args.side == "both" else (args.side,)
        keep = {f"of30_{m}_{d}{suffix}" for m in wanted for d in sides}
        unknown = wanted - set(models)
        if unknown:
            print(f"unknown entry model(s): {', '.join(sorted(unknown))}")
            return 1
        rules = {n: r for n, r in rules.items() if n in keep}
        if not rules:
            print(f"--only {args.only} matched no arm")
            return 1

    if args.stage == "2" and not args.only:
        print("Stage 2 without --only would re-run every entry model and undo the "
              "point of splitting the sweep. Pass the models that survived stage 1.")
        return 1

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"_{args.tag}" if args.tag else ""
    out_path = _OUT_DIR / f"30mof_stage{args.stage}{tag}.json"
    out: dict = {
        "symbol": args.symbol, "tf": args.tf, "bars": args.bars,
        "stage": args.stage, "start": args.start, "end": args.end,
        "fee_bps": args.fee_bps, "slippage_bps": args.slippage_bps,
        "of_lookback": args.of_lookback, "min_stop_atr": args.min_stop_atr,
        "arms": {},
    }

    engine = BacktestEngine()
    print(f"30mOF stage {args.stage} — {len(rules)} arms, {args.symbol} {args.tf}, "
          f"{args.bars} bars\n")
    started = time.time()

    for i, (name, rule) in enumerate(rules.items(), 1):
        overrides = {"fee_bps": args.fee_bps, "slippage_bps": args.slippage_bps}
        if args.min_stop_atr is not None:
            overrides["min_stop_atr"] = args.min_stop_atr
        rule = dataclasses.replace(rule, **overrides)
        t0 = time.time()
        try:
            summary = engine.run(
                args.symbol, args.tf, rule,
                bars=args.bars, start=args.start, end=args.end,
                write_journal=args.journal,
            )
        except Exception as exc:                       # noqa: BLE001
            print(f"[{i}/{len(rules)}] {name}: ОШИБКА — {exc}")
            out["arms"][name] = {"error": str(exc)}
            out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
            continue

        row = _row(summary)
        row["seconds"] = round(time.time() - t0, 1)
        row["verdict"] = _verdict(row)
        out["arms"][name] = row
        # Persist after every arm — a three-hour sweep that dies at arm 12 must
        # not take the first eleven with it.
        out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

        exp = row["expectancy"]
        ci = row["expectancy_ci"] or (None, None)
        print(
            f"[{i}/{len(rules)}] {name:26} сделок {row['trades']:4}  "
            f"W/L {row['wins']:3}/{row['losses']:3}  "
            f"E {exp if exp is not None else '—':>7}R  "
            f"CI [{ci[0]}, {ci[1]}]  PF {row['profit_factor']}  "
            f"{row['verdict']}  ({row['seconds']}s)"
        )

    print(f"\nГотово за {(time.time() - started) / 60:.1f} мин -> {out_path}")
    print("Ранжировать по нижней границе интервала, не по точечной оценке.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
