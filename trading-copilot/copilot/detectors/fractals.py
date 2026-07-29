"""
Williams Fractal detection: a candle that is the strict local extremum versus
an equal number of bars on each side (Bill Williams fractals).

  Swing high (bearish fractal): high[c] strictly greater than the `each_side`
                                highs immediately before AND after it.
  Swing low  (bullish fractal): low[c]  strictly lower than the `each_side`
                                lows immediately before AND after it.

`bars="3"` → 1 bar each side (3-bar fractal); `bars="5"` → 2 bars each side
(5-bar fractal, the default). Detection is purely the extremum — `is_swept` /
`is_broken` are post-hoc annotations of what price later did to the level, not
part of the fractal definition.
"""

import pandas as pd

TOOL_SCHEMA = {
    "name": "detect_fractals",
    "description": (
        "Find recent Williams fractal swing highs and lows on a given timeframe. "
        "A fractal is a candle that is the strict local high/low versus N bars on each "
        "side (N=1 for a 3-bar fractal, N=2 for a 5-bar fractal). "
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
            "bars": {
                "type": "string",
                "enum": ["3", "5"],
                "default": "5",
                "description": "Fractal width: '3' = 1 bar each side, '5' = 2 bars each side",
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
    bars: str = "5",
    max_results: int = 10,
) -> dict:
    """
    Scan df for Williams fractals (strict local extrema with `each_side` bars on
    each side). Returns up to max_results most recent, annotating whether price
    later swept (wick past + close back) or broke (close through) each level.
    """
    each_side = 2 if str(bars) == "5" else 1
    needed = 2 * each_side + 1
    if len(df) < needed:
        return {"status": "insufficient_data", "needed": needed, "got": len(df), "fractals": []}

    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    timestamps = df.index
    n = len(df)

    results: list[dict] = []

    for i in range(each_side, n - each_side):
        left = slice(i - each_side, i)
        right = slice(i + 1, i + 1 + each_side)

        # Swing high: strictly above every neighbour on both sides.
        if (highs[i] > highs[left]).all() and (highs[i] > highs[right]).all():
            level = highs[i]
            fut_high = highs[i + 1 :]
            fut_close = closes[i + 1 :]
            # Broken: a later candle CLOSED above the level (structural break).
            broken = bool((fut_close > level).any())
            # Swept: a later wick pierced above the level but a candle closed back
            # below it (liquidity grab) — only meaningful while still unbroken.
            swept = (not broken) and bool(((fut_high > level) & (fut_close <= level)).any())
            results.append({
                "type": "swing_high",
                "price": round(level, 2),
                "ts": timestamps[i].isoformat(),
                "is_swept": swept,
                "is_broken": broken,
                "age_bars": n - 1 - i,
            })
        # Swing low: strictly below every neighbour on both sides.
        if (lows[i] < lows[left]).all() and (lows[i] < lows[right]).all():
            level = lows[i]
            fut_low = lows[i + 1 :]
            fut_close = closes[i + 1 :]
            broken = bool((fut_close < level).any())
            swept = (not broken) and bool(((fut_low < level) & (fut_close >= level)).any())
            results.append({
                "type": "swing_low",
                "price": round(level, 2),
                "ts": timestamps[i].isoformat(),
                "is_swept": swept,
                "is_broken": broken,
                "age_bars": n - 1 - i,
            })

    # Most recent first
    results.sort(key=lambda x: x["age_bars"])
    recent = results[:max_results]

    return {
        "fractals": recent,
        "count": len(recent),
        # Intact = neither grabbed (swept) nor broken: still a pristine pool.
        "intact_count": sum(1 for f in recent if not f["is_swept"] and not f["is_broken"]),
    }
