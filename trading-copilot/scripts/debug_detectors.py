#!/usr/bin/env python3
"""
debug_detectors.py — fetch BTCUSDT spot data, run every detector,
and write one .pine file (+ one .json raw-result file) per detector
for TradingView visual debugging.

Usage (from trading-copilot/ directory):
    python scripts/debug_detectors.py                          # all detectors
    python scripts/debug_detectors.py --tf 1h --bars 500      # custom TF/bars
    python scripts/debug_detectors.py --detector detect_fvg   # single detector
    python scripts/debug_detectors.py --swing-lookback 3      # swing sensitivity
    python scripts/debug_detectors.py --list                   # names + audit status

Each output file can be pasted directly into TradingView:
    Pine Script Editor → New indicator → paste → Save → Add to chart
    (Switch chart to BTCUSDT and the matching timeframe first.)

The .json file next to each .pine holds the raw detector output —
cross-check every drawn level against it when verifying a detector.

Post P0-3/P0-5 (June 2026): market_structure / bos / order_block /
liquidity / cumulative_delta visualize the rewritten implementations
(smartmoneyconcepts-backed; structure events are close-break confirmed).
Detectors still quarantined from the LLM tool list are runnable here for
manual inspection but are tagged QUARANTINED — their output is known-bad
until their P2 rewrite lands.

Visual style: B&W design system (matches pine_script.py).
  c_fvg_fill     #f7525f 15%  — FVG / IFVG fill
  c_fvg_line     #f7525f 100% — FVG center line, IFVG border, bearish events
  c_block_active #4a4a4a 15%  — All blocks (active)
  c_block_mit    #4a4a4a 5%   — All blocks (mitigated)
  c_structure    #000000 100% — BOS, liquidity lines, swing markers
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Ensure the project root is on the path when run directly
_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from copilot.data.base import VALID_TIMEFRAMES
from copilot.data.binance import BinanceSource, fetch_ohlcv_with_delta
from copilot.detectors.market_structure import detect_market_structure
from copilot.pine.emitters import EmitContext, assemble, emit, file_header
from copilot.pine.runners import HTF_MAP, NEEDS_DELTA, NEEDS_HTF, NEEDS_MS, RunDeps
from copilot.pine.runners import run as run_detector

# Canonical order — used for --list and validation
_ALL_DETECTOR_NAMES: list[str] = [
    "detect_fvg",
    "detect_order_block",
    "detect_ifvg",
    "detect_breaker_block",
    "detect_rejection_block",
    "detect_mitigation_block",
    "detect_liquidity",
    "detect_bos",
    "detect_volume_profile",
    "detect_market_structure",
    "detect_fractals",
    "detect_fib_zones",
    "detect_compression",
    "detect_sponsored_candle",
    "check_absorption_at_poi",
    "detect_cumulative_delta",
    "check_cd_divergence_at_structure",
    "current_killzone",
    "check_multi_tf_alignment",
]

# Verification status per the June 2026 audit + P0-3/P0-5 rewrites.
# "REWRITTEN" = new implementation, needs fresh visual verification.
# "QUARANTINED" = removed from the LLM tool list, output known-bad (P2 rewrite).
_DETECTOR_STATUS: dict[str, str] = {
    "detect_fvg": "ok (audit-verified)",
    "detect_ifvg": "ok (audit-verified)",
    "detect_volume_profile": "ok (audit-verified)",
    "detect_market_structure": "REWRITTEN P0-3 — verify: state flips only on close-break events",
    "detect_bos": "REWRITTEN P0-3 — verify: every event line ends at a close through it",
    "detect_order_block": "REWRITTEN P0-3 — verify: OB = lowest-low/highest-high before the break",
    "detect_liquidity": "REWRITTEN P0-3 — verify: sweeps only at side-matching pools, close-back",
    "detect_cumulative_delta": "REWRITTEN P0-5 — verify: divergence at confirmed extreme; sweep = pool-anchored",
    "detect_fractals": "FIXED P2-1 — Williams 5-bar default; swept=wick+close-back, broken=close-through",
    "detect_fib_zones": "FIXED P2-1 — auto-infers leg direction; short OTE from swing low",
    "detect_rejection_block": "QUARANTINED — definition under manual revision by the trader (P2-1)",
    "detect_mitigation_block": "FIXED P2-2 — swing-break OB with no prior pool sweep",
    "detect_breaker_block": "FIXED P2-2 — swing-break OB, pierce = close through opposite side",
    "detect_sponsored_candle": "FIXED P2-2 — swing-break OB + sweep of nearest prior pool (R4)",
    "detect_compression": "QUARANTINED — fires on random walks (P2)",
    "check_absorption_at_poi": "QUARANTINED — broken volume threshold (P2)",
    "check_cd_divergence_at_structure": "QUARANTINED — last-bar divergence logic (P2)",
    "current_killzone": "FIXED P2-1 — weekend gate added",
    "check_multi_tf_alignment": "FIXED P2-1 — single coherent classification path",
}

_QUARANTINED = {n for n, s in _DETECTOR_STATUS.items() if s.startswith("QUARANTINED")}

# ── Pine Script helpers ───────────────────────────────────────────────────────
# The emitters themselves now live in copilot/pine/emitters.py — the copilot's
# generate_pine_script tool charts the same zones, so a single implementation
# keeps the debug view and the analysis overlay from drifting apart.

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run detectors on BTCUSDT spot and write one Pine Script file per detector.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--symbol",   default="BTCUSDT", help="Trading pair (default: BTCUSDT)")
    parser.add_argument("--tf",       default="30m",
                        choices=sorted(VALID_TIMEFRAMES),
                        help="Timeframe (default: 30m)")
    parser.add_argument("--bars",     default=500, type=int, help="Number of bars (default: 500)")
    parser.add_argument("--future",   default=50,  type=int, help="Future bars to extend zones (default: 50)")
    parser.add_argument("--out",      default="./pine_debug", help="Output directory (default: ./pine_debug)")
    parser.add_argument("--detector", default=None, metavar="NAME",
                        help="Run only this detector (default: run all).\nSee available names with --list.")
    parser.add_argument("--swing-lookback", default=None, type=int, metavar="N",
                        help="Swing pivot sensitivity for market_structure / bos /\n"
                             "order_block / liquidity (default: each detector's own default).")
    parser.add_argument("--list",     action="store_true",
                        help="Print all detector names with their June-2026 audit status and exit.")
    args = parser.parse_args()

    if args.list:
        print("Available detectors (status per June 2026 audit / P0 rewrites):")
        width = max(len(n) for n in _ALL_DETECTOR_NAMES) + 2
        for name in _ALL_DETECTOR_NAMES:
            print(f"  {name:<{width}}{_DETECTOR_STATUS.get(name, '')}")
        return

    selected: str | None = args.detector
    if selected is not None and selected not in _ALL_DETECTOR_NAMES:
        print(f"error: unknown detector '{selected}'")
        print(f"Available: {', '.join(_ALL_DETECTOR_NAMES)}")
        sys.exit(1)

    active_names: frozenset[str] = (
        frozenset({selected}) if selected else frozenset(_ALL_DETECTOR_NAMES)
    )

    symbol      = args.symbol.upper()
    tf          = args.tf
    bars        = args.bars
    future_bars = args.future
    out_dir     = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Swing sensitivity: explicit flag overrides; otherwise each detector's
    # own default is used (5 for ms/bos/ob, 3 for liquidity) so the debug
    # output matches what the MCP tools return.
    ms_lookback = args.swing_lookback or 5
    sl_kwargs: dict = (
        {"swing_lookback": args.swing_lookback} if args.swing_lookback else {}
    )

    htf = HTF_MAP.get(tf, "4h")

    print(f"Fetching {symbol} spot — {tf} × {bars} bars …")
    source = BinanceSource(market="spot")
    df = source.get_ohlc(symbol, tf, bars)
    print(f"  OK — {len(df)} bars  {df.index[0]}  →  {df.index[-1]}")

    df_delta = df
    if active_names & NEEDS_DELTA:
        print(f"Fetching delta data ({tf}) …")
        try:
            df_delta = fetch_ohlcv_with_delta(symbol, tf, bars, market="spot")
            print(f"  OK — delta columns: {list(df_delta.columns)}")
        except Exception as exc:
            print(f"  WARNING: delta fetch failed ({exc}). CD detectors will show error label.")

    htf_ms_result: dict = {}
    ltf_ms_result: dict = {}
    if active_names & (NEEDS_HTF | NEEDS_MS):
        ltf_ms_result = detect_market_structure(df)
    if active_names & NEEDS_HTF and htf != tf:
        print(f"Fetching HTF data ({htf}) for multi-TF alignment …")
        try:
            df_htf = source.get_ohlc(symbol, htf, 200)
            htf_ms_result = detect_market_structure(df_htf)
        except Exception as exc:
            print(f"  WARNING: HTF fetch failed ({exc}).")
            htf_ms_result = ltf_ms_result
    elif active_names & NEEDS_HTF:
        htf_ms_result = ltf_ms_result

    # ── Build task list ───────────────────────────────────────────────────────
    # How each detector is invoked, and how its result becomes Pine, both live in
    # copilot/pine/ — the copilot's generate_pine_script uses the same code, so a
    # zone drawn here is the zone the analysis overlay draws.
    ctx = EmitContext(
        df=df,
        bars=bars,
        future_bars=future_bars,
        swing_lookback=ms_lookback,
        htf=htf,
        ltf=tf,
    )
    deps = RunDeps(df_delta=df_delta, ltf_ms=ltf_ms_result, htf_ms=htf_ms_result)
    explicit_sl = bool(sl_kwargs)

    tasks = [
        (
            name,
            (lambda _n=name: run_detector(_n, ctx, deps, explicit_swing_lookback=explicit_sl)),
            (lambda r, _n=name: emit(_n, r, ctx)),
        )
        for name in _ALL_DETECTOR_NAMES
    ]

    tasks = [t for t in tasks if t[0] in active_names]

    print(f"\nRunning {len(tasks)} detector{'s' if len(tasks) != 1 else ''} …")
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(run_fn): name for name, run_fn, _ in tasks}
        for fut in futures:
            name = futures[fut]
            try:
                results[name] = fut.result(timeout=30)
            except Exception as exc:
                print(f"  ERROR  {name}: {exc}")
                results[name] = {"status": "error", "error": str(exc)}

    saved = 0
    errors = 0
    print()
    for name, run_fn, pine_fn in tasks:
        result = results.get(name, {})
        try:
            body  = pine_fn(result)
            hdr   = file_header(symbol, tf, name, future_bars)
            pine  = assemble(hdr, body)
            fname = f"{name}_{symbol}_{tf}.pine"
            (out_dir / fname).write_text(pine, encoding="utf-8")
            # Raw detector output — cross-check every drawn level against it
            jname = f"{name}_{symbol}_{tf}.json"
            (out_dir / jname).write_text(
                json.dumps(result, default=str, indent=2), encoding="utf-8"
            )
            status = result.get("status", "ok")
            count_key = next(
                (k for k in ("count_active", "count", "compressions") if k in result), None
            )
            count_str = f" ({result[count_key]} zones)" if count_key and isinstance(result.get(count_key), int) else ""
            q_tag = "  ⚠ QUARANTINED — output known-bad" if name in _QUARANTINED else ""
            print(f"  OK     {fname}  [{status}{count_str}]{q_tag}")
            saved += 1
        except Exception as exc:
            print(f"  ERROR  {name}: {exc}")
            errors += 1

    print(f"\n{'─'*60}")
    print(f"Saved {saved} Pine Script files (+ raw .json each) → {out_dir.resolve()}")
    if errors:
        print(f"Errors: {errors}")
    print(
        "\nHow to verify a detector:"
        "\n  1. Open TradingView and switch the chart to "
        f"{symbol} {tf}"
        "\n  2. Pine Script Editor → New indicator → paste the .pine content → Save"
        "\n  3. 'Add to chart' — zones appear anchored to the last bar"
        "\n  4. Cross-check each drawn level against the .json raw output"
        "\n  5. Check the verification hint per detector: --list shows what to look for"
        "\n\nRewritten detectors to re-verify first (P0-3/P0-5):"
        "\n  detect_market_structure  — state flips ONLY on a candle CLOSE through a level"
        "\n  detect_bos               — every event line ends at a close-break candle"
        "\n  detect_order_block       — OB candle = deepest retracement before the break"
        "\n  detect_liquidity         — sweeps: wick beyond pool + close back; breaks excluded"
        "\n  detect_cumulative_delta  — divergence at confirmed extreme; sweep is pool-anchored"
    )


if __name__ == "__main__":
    main()
