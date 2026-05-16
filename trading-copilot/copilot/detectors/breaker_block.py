"""
Breaker Block detector.

A Breaker Block is an Order Block (OB) that has been FULLY PIERCED through —
price closed past the opposite side of the OB zone — and now acts with
INVERTED polarity as a new support/resistance level.

Formation sequence:
  Bullish OB  → bullish impulse → price later closes BELOW OB low  → Bearish Breaker
  Bearish OB  → bearish impulse → price later closes ABOVE OB high → Bullish Breaker

The Breaker acts as the institution's "failed" position zone that becomes a
draw on price from the other side when price returns.

Per KB: Breaker Blocks are higher-probability than plain OBs because they
represent confirmed institutional failure — the zone has been tested and rejected once.
"""

import pandas as pd

from copilot.detectors.utils import (
    calc_atr,
    calc_ob_zone,
    extract_arrays,
    is_bearish_ob,
    is_bullish_ob,
)

TOOL_SCHEMA = {
    "name": "detect_breaker_block",
    "description": (
        "Find Breaker Blocks — Order Blocks that were fully pierced and now act with "
        "opposite polarity (bullish OB pierced downward → bearish resistance; "
        "bearish OB pierced upward → bullish support). "
        "Use when looking for high-probability reversal zones with institutional confirmation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "lookback": {"type": "integer", "default": 120},
            "max_results": {"type": "integer", "default": 6},
        },
        "required": ["symbol", "timeframe"],
    },
}


def detect_breaker_block(
    df: pd.DataFrame,
    lookback: int = 120,
    max_results: int = 6,
) -> dict:
    if len(df) < 10:
        return {
            "status": "insufficient_data",
            "needed": 10,
            "got": len(df),
            "breakers": [],
            "count": 0,
        }

    atr = calc_atr(df)
    opens, highs, lows, closes, tss = extract_arrays(df)

    breakers: list[dict] = []
    start_i = max(1, len(df) - lookback - 1)

    for i in range(start_i, len(df) - 2):
        # ── Bullish OB: bearish candle → bullish impulse ──
        if is_bullish_ob(closes, opens, highs, lows, i, atr):
            ob_high, ob_low = calc_ob_zone(highs, lows, i)

            # Pierce confirmed by a bearish FVG (3-candle pattern) that closes below ob_low.
            # Triple (j, j+1, j+2): highs[j+2] < lows[j]  AND  highs[j+2] < ob_low
            fut_highs = highs[i + 2:]
            fut_lows = lows[i + 2:]
            fut_closes = closes[i + 2:]

            first_pierce = -1
            for j in range(len(fut_highs) - 2):
                if fut_highs[j + 2] < fut_lows[j] and fut_highs[j + 2] < ob_low:
                    first_pierce = j + 2
                    break

            if first_pierce >= 0:
                after_closes = fut_closes[first_pierce + 1:]
                after_highs = fut_highs[first_pierce + 1:]

                # Still active as bearish breaker if not re-pierced upward (close above ob_high)
                exhausted = len(after_closes) > 0 and bool((after_closes > ob_high).any())
                is_tested = len(after_highs) > 0 and bool((after_highs >= ob_low).any())

                if not exhausted:
                    breakers.append({
                        "type": "bearish",  # now acts as resistance
                        "high": round(ob_high, 2),
                        "low": round(ob_low, 2),
                        "formed_ts": tss[i].isoformat(),
                        "is_tested": is_tested,
                        "age_bars": len(df) - 1 - i,
                        "original_ob_type": "bullish",
                    })

        # ── Bearish OB: bullish candle → bearish impulse ──
        if is_bearish_ob(closes, opens, highs, lows, i, atr):
            ob_high, ob_low = calc_ob_zone(highs, lows, i)

            # Pierce confirmed by a bullish FVG (3-candle pattern) that closes above ob_high.
            # Triple (j, j+1, j+2): lows[j+2] > highs[j]  AND  lows[j+2] > ob_high
            fut_highs = highs[i + 2:]
            fut_lows = lows[i + 2:]
            fut_closes = closes[i + 2:]

            first_pierce = -1
            for j in range(len(fut_lows) - 2):
                if fut_lows[j + 2] > fut_highs[j] and fut_lows[j + 2] > ob_high:
                    first_pierce = j + 2
                    break

            if first_pierce >= 0:
                after_closes = fut_closes[first_pierce + 1:]
                after_lows = fut_lows[first_pierce + 1:]

                # Still active as bullish breaker if not re-pierced downward (close below ob_low)
                exhausted = len(after_closes) > 0 and bool((after_closes < ob_low).any())
                is_tested = len(after_lows) > 0 and bool((after_lows <= ob_high).any())

                if not exhausted:
                    breakers.append({
                        "type": "bullish",  # now acts as support
                        "high": round(ob_high, 2),
                        "low": round(ob_low, 2),
                        "formed_ts": tss[i].isoformat(),
                        "is_tested": is_tested,
                        "age_bars": len(df) - 1 - i,
                        "original_ob_type": "bearish",
                    })

    # Tested breakers first (more relevant), then recency
    breakers.sort(key=lambda x: (not x["is_tested"], x["age_bars"]))
    result = breakers[:max_results]
    return {"breakers": result, "count": len(result)}
