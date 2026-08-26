"""
Pine Script v5 generator — merged overlay for the detectors the analysis
actually leaned on.

Before Aug 2026 this module hard-coded nine detectors and charted all of them
on every call, regardless of what drove the verdict. It now takes a `detectors`
list: the LLM passes the ones that materially supported its conclusion (the HTF
POI's source, the pools cited under Levels, the structure detector), and only
those become layers. Everything else — the drawing code and how each detector is
invoked — lives in `copilot/pine/`, shared with `scripts/debug_detectors.py`.

The function stays **pure** (DataFrame in, dict out, no I/O) per the detector
contract in docs/CONVENTIONS.md. Writing the .pine file is the registry's job:
`llm/tools.py` `_ARTIFACT_TOOLS` swaps the `pine_script` string for a
`pine_file` path, so hundreds of Pine lines never enter the model's context.

Usage:
  1. generate_pine_script(symbol="BTCUSDT", timeframe="1h",
                          detectors=["detect_liquidity", "detect_fvg"])
  2. Open the returned pine_file, paste into TradingView:
     Pine Script Editor → New script → paste → Save → Add to chart.
  3. Each detector is a separate toggle in the indicator's settings panel.

Zone visual style (B&W preset) is documented in copilot/pine/emitters.py.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from copilot.pine.emitters import EmitContext
from copilot.pine.overlay import OVERLAY_LAYERS, build_overlay
from copilot.pine.runners import RunDeps, run as run_detector

TOOL_SCHEMA = {
    "name": "generate_pine_script",
    "description": (
        "Generate a Pine Script v5 overlay indicator for TradingView from the detectors "
        "you consider SIGNIFICANT for this analysis, and save it to disk. "
        "Pass in `detectors` ONLY the ones that materially drove your verdict: the detector "
        "that produced the HTF POI, the one behind each level in the Levels table, and the "
        "structure detector you based the bias on. Do NOT pass detectors that returned nothing, "
        "or that you checked and then discarded — an overlay of everything is noise on the chart. "
        "One call charts one timeframe; call it a second time only if the HTF POI came from a "
        "different timeframe than the execution one. "
        "Returns the saved file path (pine_file) plus per-layer object counts — the script text "
        "itself is written to disk, not returned. Call this at the very end, after the analysis "
        "is settled, and cite pine_file in the Chart section of the report."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "e.g. BTCUSDT"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "detectors": {
                "type": "array",
                "items": {"type": "string", "enum": list(OVERLAY_LAYERS)},
                "description": (
                    "Detectors to chart as layers — only the significant ones. "
                    "Omit to chart all supported layers (rarely what you want)."
                ),
            },
            "future_bars": {
                "type": "integer",
                "default": 50,
                "description": "How many bars to the right zone boxes extend (default 50)",
            },
        },
        "required": ["symbol", "timeframe", "detectors"],
    },
}


def generate_pine_script(
    df: pd.DataFrame,
    symbol: str = "UNKNOWN",
    timeframe: str = "?",
    detectors: list[str] | None = None,
    future_bars: int = 50,
) -> dict:
    """Chart the requested detectors as one Pine v5 overlay.

    Fails soft: an unsupported detector name returns an error dict naming the
    valid layers rather than raising, so a mistaken LLM argument costs one turn
    instead of aborting the analysis.
    """
    selected = list(OVERLAY_LAYERS) if detectors is None else list(dict.fromkeys(detectors))

    unknown = [d for d in selected if d not in OVERLAY_LAYERS]
    if unknown:
        return {
            "status": "error",
            "error": (
                f"Unsupported detector(s) for charting: {', '.join(unknown)}. "
                f"Supported layers: {', '.join(OVERLAY_LAYERS)}."
            ),
            "supported_layers": list(OVERLAY_LAYERS),
        }
    if not selected:
        return {
            "status": "error",
            "error": "No detectors requested — pass the ones that drove the analysis.",
            "supported_layers": list(OVERLAY_LAYERS),
        }

    ctx = EmitContext(df=df, bars=len(df), future_bars=future_bars, ltf=timeframe)
    deps = RunDeps()

    # detect_fib_zones needs the swing pair from market structure; compute it
    # once here instead of letting the runner recompute it per call.
    if "detect_fib_zones" in selected:
        deps.ltf_ms = run_detector("detect_market_structure", ctx)

    with ThreadPoolExecutor(max_workers=max(1, len(selected))) as ex:
        futures = {name: ex.submit(run_detector, name, ctx, deps) for name in selected}
        results: dict[str, dict] = {}
        for name, fut in futures.items():
            try:
                results[name] = fut.result(timeout=30)
            except Exception as exc:  # a broken layer must not kill the chart
                results[name] = {"status": "error", "error": str(exc)}

    script, counts = build_overlay(symbol, timeframe, selected, results, ctx)
    failed = [n for n, r in results.items() if r.get("status") == "error"]

    return {
        "status": "ok",
        "pine_script": script,
        "layers": [d for d in OVERLAY_LAYERS if d in selected],
        "layer_counts": counts,
        "zone_count": sum(counts.values()),
        "failed_layers": failed,
        "instructions": (
            "Open pine_file and paste its contents into TradingView: "
            "Pine Script Editor → New script → paste → Save → Add to chart. "
            f"Switch the chart to {symbol} {timeframe} first. "
            "Each detector is a separate toggle under the indicator's Layers group."
        ),
    }
