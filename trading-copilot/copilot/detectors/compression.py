"""
Compression / LRLR (Lower Range Lower Range) detector.

Compression is a sequence of consecutively narrowing candle ranges, signalling
a contraction in volatility that typically precedes an expansion move (breakout).

LRLR: each bar's high-low range is strictly less than the prior bar's range
for `min_bars` or more consecutive bars.

Output:
  - Active compressions: sequences ending at (or near) the current bar
    → price is still in the coil, expansion imminent
  - Recent compressions: sequences that just ended (last `max_age_bars` bars)
    → breakout may be underway

Additional field `squeeze_ratio`: ratio of (compression_start_range / current_ATR),
measuring how tight the coil is. Higher ratio = stronger coil.
"""

import numpy as np
import pandas as pd

TOOL_SCHEMA = {
    "name": "detect_compression",
    "description": (
        "Find compression (LRLR) sequences — consecutive candles with narrowing ranges "
        "that precede expansion/breakout moves. "
        "Use before a killzone to identify whether price is coiling for a directional move, "
        "or after a BOS to confirm displacement energy came from a compression buildup."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "min_bars": {
                "type": "integer",
                "default": 3,
                "description": "Minimum consecutive narrowing bars to qualify",
            },
            "lookback": {"type": "integer", "default": 80},
            "max_results": {"type": "integer", "default": 3},
        },
        "required": ["symbol", "timeframe"],
    },
}


def detect_compression(
    df: pd.DataFrame,
    min_bars: int = 3,
    lookback: int = 80,
    max_results: int = 3,
) -> dict:
    if len(df) < min_bars + 2:
        return {
            "status": "insufficient_data",
            "needed": min_bars + 2,
            "got": len(df),
            "compressions": [],
            "active": False,
        }

    atr = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1])

    window = df.iloc[-lookback:]
    ranges = (window["high"] - window["low"]).values
    tss = window.index

    compressions: list[dict] = []

    # Scan for consecutive narrowing sequences
    i = 1
    while i < len(ranges):
        if ranges[i] < ranges[i - 1]:
            # Start of a narrowing sequence
            run_start = i - 1
            j = i
            while j < len(ranges) and ranges[j] < ranges[j - 1]:
                j += 1
            run_end = j - 1  # inclusive

            run_length = run_end - run_start + 1  # number of bars in narrowing seq

            if run_length >= min_bars:
                start_range = float(ranges[run_start])
                end_range = float(ranges[run_end])
                squeeze_ratio = round(start_range / end_range, 2) if end_range > 0 else 0

                # How many bars ago did this compression end?
                bars_since_end = len(window) - 1 - run_end

                compressions.append({
                    "start_ts": tss[run_start].isoformat(),
                    "end_ts": tss[run_end].isoformat(),
                    "bars": run_length,
                    "start_range": round(start_range, 4),
                    "end_range": round(end_range, 4),
                    "squeeze_ratio": squeeze_ratio,
                    "tightest_range_atr": round(end_range / atr, 3) if atr else 0,
                    "bars_since_end": bars_since_end,
                    "is_active": bars_since_end == 0,
                })

            i = j  # skip past the sequence
        else:
            i += 1

    # Sort: active first, then most recent
    compressions.sort(key=lambda x: (not x["is_active"], x["bars_since_end"]))
    result = compressions[:max_results]

    active = any(c["is_active"] for c in result)
    return {
        "compressions": result,
        "count": len(result),
        "active": active,
        "atr_14": round(atr, 4),
    }
