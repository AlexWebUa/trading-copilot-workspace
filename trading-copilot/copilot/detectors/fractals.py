"""
Fractal detection: 3-bar pattern where center candle is the local extremum.

Bullish fractal: center.low < left.low AND center.low < right.low
Bearish fractal: center.high > left.high AND center.high > right.high

Returns the N most recent intact fractals (not yet swept by price).
"""

import pandas as pd

TOOL_SCHEMA = {
    "name": "detect_fractals",
    "description": (
        "Find recent fractal swing highs and lows on a given timeframe. "
        "Fractals mark local extrema used as liquidity pools and structural pivots. "
        "Use when you need to identify swing points for BOS, structure, or liquidity pools."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "e.g. BTCUSDT"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "max_results": {
                "type": "integer",
                "default": 10,
                "description": "Max number of recent fractals to return",
            },
        },
        "required": ["symbol", "timeframe"],
    },
}


def detect_fractals(
    df: pd.DataFrame,
    max_results: int = 10,
) -> dict:
    """
    Scan df for 3-bar fractals. Returns up to max_results most recent,
    noting whether each has been swept (wick past it) by subsequent price action.
    """
    if len(df) < 3:
        return {"status": "insufficient_data", "needed": 3, "got": len(df), "fractals": []}

    highs = df["high"].values
    lows = df["low"].values
    timestamps = df.index

    results: list[dict] = []

    for i in range(1, len(df) - 1):
        # Bearish fractal (swing high)
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            swept = bool((highs[i + 1 :] > highs[i]).any())
            results.append({
                "type": "swing_high",
                "price": round(highs[i], 2),
                "ts": timestamps[i].isoformat(),
                "is_swept": swept,
                "age_bars": len(df) - 1 - i,
            })
        # Bullish fractal (swing low)
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            swept = bool((lows[i + 1 :] < lows[i]).any())
            results.append({
                "type": "swing_low",
                "price": round(lows[i], 2),
                "ts": timestamps[i].isoformat(),
                "is_swept": swept,
                "age_bars": len(df) - 1 - i,
            })

    # Most recent first
    results.sort(key=lambda x: x["age_bars"])
    recent = results[:max_results]

    return {
        "fractals": recent,
        "count": len(recent),
        "intact_count": sum(1 for f in recent if not f["is_swept"]),
    }
