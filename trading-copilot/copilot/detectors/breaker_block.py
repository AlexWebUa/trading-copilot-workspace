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

from copilot.detectors.utils import extract_arrays
from copilot.detectors.order_block import scan_order_blocks

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
            "swing_lookback": {"type": "integer", "default": 5},
        },
        "required": ["symbol", "timeframe"],
    },
}


def detect_breaker_block(
    df: pd.DataFrame,
    lookback: int = 120,
    max_results: int = 6,
    swing_lookback: int = 5,
) -> dict:
    if len(df) < 10:
        return {
            "status": "insufficient_data",
            "needed": 10,
            "got": len(df),
            "breakers": [],
            "count": 0,
        }

    _, highs, lows, closes, tss = extract_arrays(df)
    n = len(df)

    # Single OB universe (R3). A breaker is a swing-break OB later fully pierced —
    # confirmed by a CLOSE through the opposite boundary, FVG or not (P2-2).
    breakers: list[dict] = []
    for c in scan_order_blocks(df, swing_lookback=swing_lookback, lookback=lookback):
        ob_high, ob_low, ob_idx, brk = c["ob_high"], c["ob_low"], c["ob_idx"], c["break_idx"]
        fut_closes = closes[brk + 1:]

        if c["type"] == "bullish":
            # Pierce = a later close BELOW the OB low → bearish breaker (resistance).
            rel = np.where(fut_closes < ob_low)[0]
            if len(rel) == 0:
                continue
            pierce_idx = brk + 1 + int(rel[0])
            after_closes = closes[pierce_idx + 1:]
            after_highs = highs[pierce_idx + 1:]
            # Exhausted if price later closes back above the OB high.
            if len(after_closes) and bool((after_closes > ob_high).any()):
                continue
            is_tested = len(after_highs) > 0 and bool((after_highs >= ob_low).any())
            breakers.append({
                "type": "bearish",            # now acts as resistance
                "high": round(ob_high, 2),
                "low": round(ob_low, 2),
                "formed_ts": tss[ob_idx].isoformat(),
                "pierce_ts": tss[pierce_idx].isoformat(),
                "is_tested": is_tested,
                "age_bars": n - 1 - ob_idx,
                "original_ob_type": "bullish",
            })
        else:
            # Pierce = a later close ABOVE the OB high → bullish breaker (support).
            rel = np.where(fut_closes > ob_high)[0]
            if len(rel) == 0:
                continue
            pierce_idx = brk + 1 + int(rel[0])
            after_closes = closes[pierce_idx + 1:]
            after_lows = lows[pierce_idx + 1:]
            if len(after_closes) and bool((after_closes < ob_low).any()):
                continue
            is_tested = len(after_lows) > 0 and bool((after_lows <= ob_high).any())
            breakers.append({
                "type": "bullish",            # now acts as support
                "high": round(ob_high, 2),
                "low": round(ob_low, 2),
                "formed_ts": tss[ob_idx].isoformat(),
                "pierce_ts": tss[pierce_idx].isoformat(),
                "is_tested": is_tested,
                "age_bars": n - 1 - ob_idx,
                "original_ob_type": "bearish",
            })

    # Tested breakers first (more relevant), then recency
    breakers.sort(key=lambda x: (not x["is_tested"], x["age_bars"]))
    result = breakers[:max_results]
    return {"breakers": result, "count": len(result)}
