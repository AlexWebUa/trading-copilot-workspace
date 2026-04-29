"""
Break of Structure (BOS) / Market Structure Shift (MSS) detector.

Terminology (per KB):
- BOS  : break in the trend direction (continuation); new HH in bull trend or LL in bear trend.
- cBOS : confirmed BOS — same as BOS but with clear displacement (large range candle).
- MSS  : break AGAINST the trend (structure shift / reversal signal).

Detection rule: candle CLOSE must breach the prior swing extreme (not just a wick).
"""

import numpy as np
import pandas as pd

from copilot.detectors.market_structure import _find_swings

TOOL_SCHEMA = {
    "name": "detect_bos",
    "description": (
        "Detect the most recent Break of Structure (BOS), Market Structure Shift (MSS), "
        "or Continuation BOS (cBOS) on a given timeframe. "
        "BOS confirms trend continuation; MSS signals potential reversal. "
        "Use after detect_market_structure to confirm if structure is still intact or has shifted."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "swing_lookback": {"type": "integer", "default": 5},
        },
        "required": ["symbol", "timeframe"],
    },
}


def detect_bos(df: pd.DataFrame, swing_lookback: int = 5) -> dict:
    min_bars = swing_lookback * 2 + 5
    if len(df) < min_bars:
        return {"status": "insufficient_data", "needed": min_bars, "got": len(df)}

    swings = _find_swings(df, swing_lookback)
    highs = [s for s in swings if s["type"] == "high"]
    lows = [s for s in swings if s["type"] == "low"]

    if not highs or not lows:
        return {"type": "none", "direction": "none", "broken_level": None, "break_ts": None,
                "displacement_candles": 0, "displacement_atr_multiple": 0.0}

    last_h = highs[-1]
    last_l = lows[-1]

    closes = df["close"].values
    tss = df.index
    atr = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1])

    # Scan backwards to find the MOST RECENT structural break by close.
    # Scanning forward would stop at the first break (e.g. a cBOS mid-trend)
    # and miss a later MSS — the opposite of what the trader needs.
    bos_event = None
    scan_start = max(swing_lookback, 10)
    for i in range(len(df) - 1, scan_start, -1):
        c = closes[i]
        ts = tss[i]

        # MSS: close breaks below the most recent swing LOW (bearish reversal signal)
        if c < last_l["price"] and pd.Timestamp(last_l["ts"]) < ts:
            displacement = _count_displacement(closes, i)
            bos_event = {
                "type": "MSS",
                "direction": "bearish",
                "broken_level": round(last_l["price"], 2),
                "break_ts": ts.isoformat(),
                "displacement_candles": displacement,
                "displacement_atr_multiple": round(
                    abs(c - last_l["price"]) / atr if atr else 0, 2
                ),
            }
            break

        # BOS/cBOS: close breaks above the most recent swing HIGH (bullish continuation)
        if c > last_h["price"] and pd.Timestamp(last_h["ts"]) < ts:
            displacement = _count_displacement(closes, i)
            bos_event = {
                "type": "BOS" if abs(c - last_h["price"]) < 2 * atr else "cBOS",
                "direction": "bullish",
                "broken_level": round(last_h["price"], 2),
                "break_ts": ts.isoformat(),
                "displacement_candles": displacement,
                "displacement_atr_multiple": round(
                    abs(c - last_h["price"]) / atr if atr else 0, 2
                ),
            }
            break

    if bos_event:
        return bos_event

    return {
        "type": "none",
        "direction": "none",
        "broken_level": None,
        "break_ts": None,
        "displacement_candles": 0,
        "displacement_atr_multiple": 0.0,
    }


def _count_displacement(closes: "np.ndarray", break_idx: int, window: int = 5) -> int:
    """Count consecutive candles moving in the break direction after the break."""
    direction = 1 if closes[break_idx] > closes[break_idx - 1] else -1
    count = 0
    for j in range(break_idx, min(break_idx + window, len(closes) - 1)):
        if (closes[j + 1] - closes[j]) * direction > 0:
            count += 1
        else:
            break
    return count
