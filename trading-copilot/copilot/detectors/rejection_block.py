"""
Rejection Block detector.

A Rejection Block is a 2-candle pattern where a large directional candle (C1)
is immediately followed by a candle (C2) whose BODY fully engulfs C1's body
in the opposite direction.

  Bearish Rejection Block:
    C1: bullish (close > open), meaningful body size
    C2: bearish close goes BELOW C1's body low (min(open, close) of C1)
    Zone: [C1 body low, C1 body high] → now acts as bearish resistance

  Bullish Rejection Block:
    C1: bearish (close < open), meaningful body size
    C2: bullish close goes ABOVE C1's body high (max(open, close) of C1)
    Zone: [C1 body low, C1 body high] → now acts as bullish support

Interpretation: the institutional "rejection" of the C1 impulse shows strong
counter-directional interest. The C1 body becomes the zone price will respect.
"""

import pandas as pd

from copilot.detectors.utils import calc_atr, extract_arrays

TOOL_SCHEMA = {
    "name": "detect_rejection_block",
    "description": (
        "Find Rejection Blocks — 2-candle engulfing reversal patterns where a large "
        "directional candle is immediately engulfed by the next candle in the opposite direction. "
        "The C1 body zone acts as institutional support/resistance. "
        "Use to identify sharp reversal zones that formed quickly without build-up."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "min_body_atr": {
                "type": "number",
                "default": 0.3,
                "description": "C1 minimum body size as fraction of ATR(14)",
            },
            "lookback": {"type": "integer", "default": 100},
            "max_results": {"type": "integer", "default": 6},
        },
        "required": ["symbol", "timeframe"],
    },
}


def detect_rejection_block(
    df: pd.DataFrame,
    min_body_atr: float = 0.3,
    lookback: int = 100,
    max_results: int = 6,
) -> dict:
    if len(df) < 5:
        return {
            "status": "insufficient_data",
            "needed": 5,
            "got": len(df),
            "blocks": [],
            "count": 0,
        }

    atr = calc_atr(df)
    min_body = atr * min_body_atr

    opens, highs, lows, closes, tss = extract_arrays(df)

    blocks: list[dict] = []
    start_i = max(1, len(df) - lookback - 1)

    for i in range(start_i, len(df) - 1):
        c1_body_high, c1_body_low = max(opens[i], closes[i]), min(opens[i], closes[i])
        c1_body_size = c1_body_high - c1_body_low

        if c1_body_size < min_body:
            continue  # C1 too small — not a meaningful impulse

        c2_close = closes[i + 1]

        # ── Bearish Rejection Block: bullish C1, C2 closes below C1 body low ──
        if closes[i] > opens[i] and c2_close < c1_body_low:
            future_highs = highs[i + 2:]
            future_closes = closes[i + 2:]

            # Mitigated if price later closes above c1_body_high
            is_mitigated = len(future_closes) > 0 and bool((future_closes > c1_body_high).any())
            # Tested if price wicks back up into the zone without closing above it
            is_tested = len(future_highs) > 0 and bool(
                (future_highs >= c1_body_low).any() and not (future_closes > c1_body_high).any()
            )

            blocks.append({
                "type": "bearish",
                "high": round(c1_body_high, 2),
                "low": round(c1_body_low, 2),
                "formed_ts": tss[i].isoformat(),
                "c1_body_size_atr": round(c1_body_size / atr, 2) if atr else 0,
                "is_mitigated": is_mitigated,
                "is_tested": is_tested,
                "age_bars": len(df) - 1 - i,
            })

        # ── Bullish Rejection Block: bearish C1, C2 closes above C1 body high ──
        elif closes[i] < opens[i] and c2_close > c1_body_high:
            future_lows = lows[i + 2:]
            future_closes = closes[i + 2:]

            # Mitigated if price later closes below c1_body_low
            is_mitigated = len(future_closes) > 0 and bool((future_closes < c1_body_low).any())
            is_tested = len(future_lows) > 0 and bool(
                (future_lows <= c1_body_high).any() and not (future_closes < c1_body_low).any()
            )

            blocks.append({
                "type": "bullish",
                "high": round(c1_body_high, 2),
                "low": round(c1_body_low, 2),
                "formed_ts": tss[i].isoformat(),
                "c1_body_size_atr": round(c1_body_size / atr, 2) if atr else 0,
                "is_mitigated": is_mitigated,
                "is_tested": is_tested,
                "age_bars": len(df) - 1 - i,
            })

    # Unmitigated and untested first (most relevant), then recency
    blocks.sort(key=lambda x: (x["is_mitigated"], not x["is_tested"], x["age_bars"]))
    result = blocks[:max_results]
    return {"blocks": result, "count": len(result)}
