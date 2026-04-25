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

import numpy as np
import pandas as pd

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

_IMPULSE_ATR_THRESHOLD = 1.5


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

    atr = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1])
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    tss = df.index

    breakers: list[dict] = []
    start_i = max(1, len(df) - lookback - 1)

    for i in range(start_i, len(df) - 2):
        impulse_range = highs[i + 1] - lows[i + 1]

        # ── Bullish OB: bearish candle → bullish impulse ──
        if closes[i] < opens[i] and closes[i + 1] > highs[i] and impulse_range > _IMPULSE_ATR_THRESHOLD * atr:
            ob_high = max(opens[i], closes[i])
            ob_low = min(opens[i], closes[i])

            # Was the OB fully pierced? (close below ob_low after impulse)
            fut_closes = closes[i + 2:]
            fut_highs = highs[i + 2:]
            pierce_mask = fut_closes < ob_low

            if pierce_mask.any():
                first_pierce = int(np.argmax(pierce_mask))
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
        if closes[i] > opens[i] and closes[i + 1] < lows[i] and impulse_range > _IMPULSE_ATR_THRESHOLD * atr:
            ob_high = max(opens[i], closes[i])
            ob_low = min(opens[i], closes[i])

            # Was the OB fully pierced? (close above ob_high after impulse)
            fut_closes = closes[i + 2:]
            fut_lows = lows[i + 2:]
            pierce_mask = fut_closes > ob_high

            if pierce_mask.any():
                first_pierce = int(np.argmax(pierce_mask))
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
