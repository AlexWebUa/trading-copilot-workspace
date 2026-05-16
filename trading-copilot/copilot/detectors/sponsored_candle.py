"""
Sponsored Candle detector.

A Sponsored Candle is an Order Block (OB) that was IMMEDIATELY PRECEDED by
a confirmed liquidity sweep. The sequence:

  Sellside sweep (wick below prior low, close back above) → bearish OB candle → bullish impulse
  Buyside  sweep (wick above prior high, close back below) → bullish OB candle → bearish impulse

Why it matters (per KB):
  The sweep "sponsored" the institutional order — stops were taken, fuel was collected.
  This is the highest-probability OB variant because institutions used the sweep
  to accumulate/distribute before the impulse.

Detection:
  1. Find OB patterns (opposing candle + impulse close) — same as detect_order_block.
  2. In the `sweep_window` bars BEFORE the OB candle, look for a confirmed sweep:
     - Bullish OB:  wick below OB low + close back above OB low (sellside swept)
     - Bearish OB:  wick above OB high + close back below OB high (buyside swept)
  3. Return sponsored OBs that are still unmitigated.
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
    "name": "detect_sponsored_candle",
    "description": (
        "Find Sponsored Candles — Order Blocks immediately preceded by a confirmed liquidity sweep. "
        "These are the highest-quality OBs: institutions swept stops then entered the impulse. "
        "Use to identify setups where both a sweep AND an OB are present for maximum confluence."
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
                "default": 5,
                "description": "Bars before OB to scan for the sponsoring sweep",
            },
            "max_results": {"type": "integer", "default": 4},
        },
        "required": ["symbol", "timeframe"],
    },
}


def detect_sponsored_candle(
    df: pd.DataFrame,
    lookback: int = 100,
    sweep_window: int = 5,
    max_results: int = 4,
) -> dict:
    if len(df) < 10:
        return {
            "status": "insufficient_data",
            "needed": 10,
            "got": len(df),
            "candles": [],
            "count": 0,
        }

    atr = calc_atr(df)
    opens, highs, lows, closes, tss = extract_arrays(df)

    sponsored: list[dict] = []
    start_i = max(sweep_window + 1, len(df) - lookback - 1)

    for i in range(start_i, len(df) - 2):
        # ── Bullish OB: bearish candle → bullish impulse ──
        if is_bullish_ob(closes, opens, highs, lows, i, atr):
            ob_high, ob_low = calc_ob_zone(highs, lows, i)

            # Check for sellside sweep before the OB:
            # A bar where low < ob_low AND close > ob_low (wick below, closed back)
            pre_start = max(0, i - sweep_window)
            sweep_found, sweep_bar_offset = find_sweep(lows[pre_start:i], closes[pre_start:i], ob_low, "sellside")

            if not sweep_found:
                continue  # No sponsoring sweep → not a sponsored candle

            is_mitigated = is_zone_mitigated(ob_high, ob_low, lows[i + 2:], "bullish")

            sponsored.append({
                "ob_type": "bullish",
                "high": round(ob_high, 2),
                "low": round(ob_low, 2),
                "formed_ts": tss[i].isoformat(),
                "sweep_ts": tss[pre_start + sweep_bar_offset].isoformat(),
                "sweep_side": "sellside",
                "is_mitigated": is_mitigated,
                "age_bars": len(df) - 1 - i,
            })

        # ── Bearish OB: bullish candle → bearish impulse ──
        if is_bearish_ob(closes, opens, highs, lows, i, atr):
            ob_high, ob_low = calc_ob_zone(highs, lows, i)

            # Check for buyside sweep before the OB:
            # A bar where high > ob_high AND close < ob_high (wick above, closed back)
            pre_start = max(0, i - sweep_window)
            sweep_found, sweep_bar_offset = find_sweep(highs[pre_start:i], closes[pre_start:i], ob_high, "buyside")

            if not sweep_found:
                continue

            is_mitigated = is_zone_mitigated(ob_high, ob_low, highs[i + 2:], "bearish")

            sponsored.append({
                "ob_type": "bearish",
                "high": round(ob_high, 2),
                "low": round(ob_low, 2),
                "formed_ts": tss[i].isoformat(),
                "sweep_ts": tss[pre_start + sweep_bar_offset].isoformat(),
                "sweep_side": "buyside",
                "is_mitigated": is_mitigated,
                "age_bars": len(df) - 1 - i,
            })

    # Unmitigated first, then recency
    sponsored.sort(key=lambda x: (x["is_mitigated"], x["age_bars"]))
    result = sponsored[:max_results]
    return {"candles": result, "count": len(result)}
