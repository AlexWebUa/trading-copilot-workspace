"""
Inverted Fair Value Gap (IFVG) detector.

An IFVG is a standard FVG that was FULLY PIERCED — price closed completely
through the zone — and now acts with INVERTED polarity:
  Bullish FVG fully pierced downward → becomes bearish resistance zone
  Bearish FVG fully pierced upward   → becomes bullish support zone

Detection steps:
  1. Find all 3-candle FVG patterns in the lookback window.
  2. Check if subsequent price closed through the zone (fill_state == "filled").
  3. After the pierce, check if zone is still active (not re-pierced from the new side).
  4. Record whether price has returned to test the zone post-inversion.

Usage: call after detect_fvg when you need to identify polarity-flipped zones
that now act as POIs from the opposite direction.
"""

import numpy as np
import pandas as pd

TOOL_SCHEMA = {
    "name": "detect_ifvg",
    "description": (
        "Find Inverted Fair Value Gaps (IFVGs) — FVGs that were fully pierced and "
        "now act with opposite polarity (bullish FVG → bearish resistance, and vice versa). "
        "Use when the regular FVG list shows no active zones but you suspect a polarity-flipped "
        "zone is acting as resistance or support."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "e.g. BTCUSDT"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "min_width_atr": {
                "type": "number",
                "default": 0.1,
                "description": "Minimum zone width as fraction of ATR(14)",
            },
            "lookback": {
                "type": "integer",
                "default": 300,
                "description": "Bars to scan for original FVG patterns",
            },
            "max_results": {"type": "integer", "default": 6},
        },
        "required": ["symbol", "timeframe"],
    },
}


def detect_ifvg(
    df: pd.DataFrame,
    min_width_atr: float = 0.1,
    lookback: int = 300,
    max_results: int = 6,
) -> dict:
    if len(df) < 5:
        return {
            "status": "insufficient_data",
            "needed": 5,
            "got": len(df),
            "ifvgs": [],
            "count": 0,
        }

    atr = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1])
    min_width = atr * min_width_atr

    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    tss = df.index

    ifvgs: list[dict] = []
    # Need at least 2 bars after C2 to check for pierce
    start_i = max(0, len(df) - lookback - 2)

    for i in range(start_i, len(df) - 4):
        c0_high, c0_low = highs[i], lows[i]
        c2_high, c2_low = highs[i + 2], lows[i + 2]

        # Standard FVG detection
        if c2_low > c0_high:
            upper, lower = c2_low, c0_high
            orig_type = "bullish"
            inv_type = "bearish"  # after pierce, acts as resistance
        elif c2_high < c0_low:
            upper, lower = c0_low, c2_high
            orig_type = "bearish"
            inv_type = "bullish"  # after pierce, acts as support
        else:
            continue

        if (upper - lower) < min_width:
            continue

        # Price action after C2
        fut_start = i + 3
        fut_closes = closes[fut_start:]
        fut_highs = highs[fut_start:]
        fut_lows = lows[fut_start:]

        if len(fut_closes) == 0:
            continue

        # Check if the zone was fully pierced (close past the zone)
        if orig_type == "bullish":
            pierce_mask = fut_closes < lower  # closed below the zone bottom
        else:
            pierce_mask = fut_closes > upper  # closed above the zone top

        if not pierce_mask.any():
            continue  # never fully pierced → not an IFVG

        first_pierce_idx = int(np.argmax(pierce_mask))

        # After the pierce, check if IFVG is still active
        after_closes = fut_closes[first_pierce_idx + 1:]
        after_highs = fut_highs[first_pierce_idx + 1:]
        after_lows = fut_lows[first_pierce_idx + 1:]

        if orig_type == "bullish":
            # Now a bearish resistance zone (upper side)
            # Exhausted if price later closed ABOVE the zone (re-pierced upward)
            exhausted = len(after_closes) > 0 and bool((after_closes > upper).any())
            # Tested if price wicked back into the zone from below
            is_tested = len(after_highs) > 0 and bool((after_highs >= lower).any())
        else:
            # Now a bullish support zone (lower side)
            # Exhausted if price later closed BELOW the zone (re-pierced downward)
            exhausted = len(after_closes) > 0 and bool((after_closes < lower).any())
            # Tested if price wicked back into the zone from above
            is_tested = len(after_lows) > 0 and bool((after_lows <= upper).any())

        if exhausted:
            continue

        ifvgs.append({
            "type": inv_type,
            "upper": round(upper, 2),
            "lower": round(lower, 2),
            "formed_ts": tss[i + 1].isoformat(),  # original impulse candle
            "is_tested": is_tested,
            "age_bars": len(df) - 1 - (i + 2),
            "width_atr_fraction": round((upper - lower) / atr, 3) if atr else 0,
        })

    # Tested IFVGs first (price has shown interest), then recency
    ifvgs.sort(key=lambda x: (not x["is_tested"], x["age_bars"]))
    result = ifvgs[:max_results]
    return {"ifvgs": result, "count": len(result)}
