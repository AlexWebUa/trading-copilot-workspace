"""
Order Block (OB) detector.

An OB is the last candle opposite in direction to an ensuing impulsive move
that caused a BOS or significant structural break.

Bullish OB: last bearish (red) candle before an impulsive bullish move.
Bearish OB: last bullish (green) candle before an impulsive bearish move.

Quality signal (per KB): OB is higher quality if an FVG follows immediately after it.

State:
  unmitigated : price has not returned to the OB zone
  mitigated   : price touched the OB zone (≥50% of zone body visited)
"""

import pandas as pd

from copilot.detectors.fvg import detect_fvg

TOOL_SCHEMA = {
    "name": "detect_order_block",
    "description": (
        "Find active Order Blocks (demand/supply zones where institutions placed orders). "
        "Each OB is the last opposing candle before an impulsive structural move. "
        "Use to identify high-probability POIs for entries and reactions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "lookback": {
                "type": "integer",
                "default": 100,
                "description": "How many bars back to scan for OBs",
            },
            "max_results": {"type": "integer", "default": 6},
        },
        "required": ["symbol", "timeframe"],
    },
}

_IMPULSE_ATR_THRESHOLD = 1.5  # next candle must be > 1.5x ATR to qualify as impulse


def detect_order_block(
    df: pd.DataFrame,
    lookback: int = 100,
    max_results: int = 6,
) -> dict:
    if len(df) < 10:
        return {"status": "insufficient_data", "needed": 10, "got": len(df), "obs": [], "count": 0}

    atr = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1])
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    tss = df.index

    current_price = float(closes[-1])
    start_i = max(1, len(df) - lookback - 1)
    obs: list[dict] = []

    for i in range(start_i, len(df) - 2):
        candle_range = highs[i] - lows[i]
        next_range = highs[i + 1] - lows[i + 1]

        # Bullish OB: bearish candle (close < open) followed by bullish impulse
        is_bearish_candle = closes[i] < opens[i]
        is_bullish_impulse = (closes[i + 1] > highs[i] and next_range > _IMPULSE_ATR_THRESHOLD * atr)

        if is_bearish_candle and is_bullish_impulse:
            ob_high = max(opens[i], closes[i])
            ob_low = min(opens[i], closes[i])
            mitigated = _is_mitigated("bullish", ob_high, ob_low, lows[i + 2:])
            has_fvg = _check_fvg_after(df, i + 1, "bullish")
            distance = round(abs(current_price - ob_low) / atr, 2) if atr else 0
            obs.append({
                "type": "bullish",
                "high": round(ob_high, 2),
                "low": round(ob_low, 2),
                "formed_ts": tss[i].isoformat(),
                "has_fvg_after": has_fvg,
                "is_mitigated": mitigated,
                "distance_atr": distance,
                "age_bars": len(df) - 1 - i,
            })

        # Bearish OB: bullish candle (close > open) followed by bearish impulse
        is_bullish_candle = closes[i] > opens[i]
        is_bearish_impulse = (closes[i + 1] < lows[i] and next_range > _IMPULSE_ATR_THRESHOLD * atr)

        if is_bullish_candle and is_bearish_impulse:
            ob_high = max(opens[i], closes[i])
            ob_low = min(opens[i], closes[i])
            mitigated = _is_mitigated("bearish", ob_high, ob_low, highs[i + 2:])
            has_fvg = _check_fvg_after(df, i + 1, "bearish")
            distance = round(abs(current_price - ob_high) / atr, 2) if atr else 0
            obs.append({
                "type": "bearish",
                "high": round(ob_high, 2),
                "low": round(ob_low, 2),
                "formed_ts": tss[i].isoformat(),
                "has_fvg_after": has_fvg,
                "is_mitigated": mitigated,
                "distance_atr": distance,
                "age_bars": len(df) - 1 - i,
            })

    # Sort: unmitigated first, then by recency
    obs.sort(key=lambda x: (x["is_mitigated"], x["age_bars"]))
    trimmed = obs[:max_results]
    return {"obs": trimmed, "count": len(trimmed)}


def _is_mitigated(
    ob_type: str, ob_high: float, ob_low: float, future_prices: "np.ndarray"
) -> bool:
    midpoint = (ob_high + ob_low) / 2
    if ob_type == "bullish":
        return bool((future_prices <= midpoint).any())
    else:
        return bool((future_prices >= midpoint).any())


def _check_fvg_after(df: pd.DataFrame, impulse_idx: int, ob_type: str) -> bool:
    """Check if an FVG exists immediately after the OB impulse candle."""
    slice_end = min(impulse_idx + 5, len(df))
    if slice_end - impulse_idx < 3:
        return False
    result = detect_fvg(df.iloc[impulse_idx : slice_end], max_age_bars=10)
    fvgs = result.get("fvgs", [])
    return any(f["type"] == ob_type for f in fvgs)
