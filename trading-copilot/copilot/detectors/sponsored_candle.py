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

import numpy as np
import pandas as pd

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

_IMPULSE_ATR_THRESHOLD = 1.5


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

    atr = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1])
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    tss = df.index

    sponsored: list[dict] = []
    start_i = max(sweep_window + 1, len(df) - lookback - 1)

    for i in range(start_i, len(df) - 2):
        impulse_range = highs[i + 1] - lows[i + 1]

        # ── Bullish OB: bearish candle → bullish impulse ──
        if closes[i] < opens[i] and closes[i + 1] > highs[i] and impulse_range > _IMPULSE_ATR_THRESHOLD * atr:
            ob_high = max(opens[i], closes[i])
            ob_low = min(opens[i], closes[i])

            # Check for sellside sweep before the OB:
            # A bar where low < ob_low AND close > ob_low (wick below, closed back)
            pre_start = max(0, i - sweep_window)
            pre_lows = lows[pre_start:i]
            pre_closes = closes[pre_start:i]

            sweep_found, sweep_bar_offset = _find_sweep(pre_lows, pre_closes, ob_low, side="sellside")

            if not sweep_found:
                continue  # No sponsoring sweep → not a sponsored candle

            future_closes = closes[i + 2:]
            midpoint = (ob_high + ob_low) / 2
            is_mitigated = len(future_closes) > 0 and bool((future_closes <= midpoint).any())

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
        if closes[i] > opens[i] and closes[i + 1] < lows[i] and impulse_range > _IMPULSE_ATR_THRESHOLD * atr:
            ob_high = max(opens[i], closes[i])
            ob_low = min(opens[i], closes[i])

            # Check for buyside sweep before the OB:
            # A bar where high > ob_high AND close < ob_high (wick above, closed back)
            pre_start = max(0, i - sweep_window)
            pre_highs = highs[pre_start:i]
            pre_closes = closes[pre_start:i]

            sweep_found, sweep_bar_offset = _find_sweep(pre_highs, pre_closes, ob_high, side="buyside")

            if not sweep_found:
                continue

            future_closes = closes[i + 2:]
            midpoint = (ob_high + ob_low) / 2
            is_mitigated = len(future_closes) > 0 and bool((future_closes >= midpoint).any())

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


def _find_sweep(
    wicks: np.ndarray,
    closes: np.ndarray,
    level: float,
    side: str,
) -> tuple[bool, int]:
    """
    Find the first bar that sweeps the given level and closes back.

    Returns (found, bar_index_in_slice).
    """
    for j in range(len(wicks)):
        if side == "sellside":
            if wicks[j] < level and closes[j] > level:
                return True, j
        else:  # buyside
            if wicks[j] > level and closes[j] < level:
                return True, j
    return False, -1
