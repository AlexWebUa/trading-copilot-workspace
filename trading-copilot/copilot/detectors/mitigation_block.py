"""
Mitigation Block detector.

A Mitigation Block is an Order Block formed by an impulsive structural break
that occurred WITHOUT sweeping the opposing liquidity pool first.

Standard ICT flow:
  Sellside liquidity swept → bullish OB → impulse up   (sponsored/clean)
  Buyside  liquidity swept → bearish OB → impulse down (sponsored/clean)

Mitigation Block flow (the anomaly):
  Bullish impulse WITHOUT first sweeping the sellside low  → Bullish Mitigation Block
  Bearish impulse WITHOUT first sweeping the buyside high  → Bearish Mitigation Block

Consequence: because the opposing liquidity was NOT collected before the move,
institutions MUST return to the Mitigation Block zone to complete their orders
("mitigate" the remaining fills). This makes the zone a high-probability draw.

Detection logic:
  1. Same OB pattern as detect_order_block (opposing candle + impulse close).
  2. In the `sweep_window` bars BEFORE the OB candle, check whether the opposing
     liquidity pool (local swing extreme) was swept (wick + close-back confirmation).
  3. If NO sweep preceded the OB → Mitigation Block.
  4. Return unmitigated blocks (zone midpoint not yet visited by any wick).
"""

import pandas as pd

from copilot.detectors.utils import (
    IMPULSE_ATR_THRESHOLD,
    calc_atr,
    calc_ob_zone,
    extract_arrays,
    find_sweep,
    is_bearish_ob,
    is_bullish_ob,
    is_zone_mitigated,
)

TOOL_SCHEMA = {
    "name": "detect_mitigation_block",
    "description": (
        "Find Mitigation Blocks — Order Blocks formed without a prior liquidity sweep. "
        "These zones are high-probability because institutions must return to complete "
        "their orders ('mitigate'). "
        "Use when the market made an impulsive move but opposing stops were not taken first."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "lookback": {"type": "integer", "default": 100},
            "sweep_window": {
                "type": "integer",
                "default": 8,
                "description": "Bars before the OB to check for a prior sweep",
            },
            "max_results": {"type": "integer", "default": 5},
        },
        "required": ["symbol", "timeframe"],
    },
}


def detect_mitigation_block(
    df: pd.DataFrame,
    lookback: int = 100,
    sweep_window: int = 8,
    max_results: int = 5,
) -> dict:
    if len(df) < 12:
        return {
            "status": "insufficient_data",
            "needed": 12,
            "got": len(df),
            "blocks": [],
            "count": 0,
        }

    atr = calc_atr(df)
    opens, highs, lows, closes, tss = extract_arrays(df)

    blocks: list[dict] = []
    start_i = max(sweep_window + 1, len(df) - lookback - 1)

    for i in range(start_i, len(df) - 2):
        # ── Bullish OB: bearish candle → bullish impulse ──
        if is_bullish_ob(closes, opens, highs, lows, i, atr):
            ob_high, ob_low = calc_ob_zone(highs, lows, i)

            # Look for a sellside sweep in the window before the OB:
            # A wick below ob_low that closes back above ob_low → sellside swept
            pre_start = max(0, i - sweep_window)
            prior_sweep, _ = find_sweep(lows[pre_start:i], closes[pre_start:i], ob_low, "sellside")

            if prior_sweep:
                continue  # Liquidity was swept → regular sponsored OB, skip

            is_mitigated = is_zone_mitigated(ob_high, ob_low, lows[i + 2:], "bullish")

            blocks.append({
                "type": "bullish",
                "high": round(ob_high, 2),
                "low": round(ob_low, 2),
                "formed_ts": tss[i].isoformat(),
                "is_mitigated": is_mitigated,
                "age_bars": len(df) - 1 - i,
                "note": "move initiated without prior sellside sweep",
            })

        # ── Bearish OB: bullish candle → bearish impulse ──
        if is_bearish_ob(closes, opens, highs, lows, i, atr):
            ob_high, ob_low = calc_ob_zone(highs, lows, i)

            # Look for a buyside sweep in the window before the OB:
            # A wick above ob_high that closes back below ob_high → buyside swept
            pre_start = max(0, i - sweep_window)
            prior_sweep, _ = find_sweep(highs[pre_start:i], closes[pre_start:i], ob_high, "buyside")

            if prior_sweep:
                continue  # Liquidity swept → regular sponsored OB, skip

            is_mitigated = is_zone_mitigated(ob_high, ob_low, highs[i + 2:], "bearish")

            blocks.append({
                "type": "bearish",
                "high": round(ob_high, 2),
                "low": round(ob_low, 2),
                "formed_ts": tss[i].isoformat(),
                "is_mitigated": is_mitigated,
                "age_bars": len(df) - 1 - i,
                "note": "move initiated without prior buyside sweep",
            })

    # Unmitigated first (still need to be revisited), then recency
    blocks.sort(key=lambda x: (x["is_mitigated"], x["age_bars"]))
    result = blocks[:max_results]
    return {"blocks": result, "count": len(result)}
