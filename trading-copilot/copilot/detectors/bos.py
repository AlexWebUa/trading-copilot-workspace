"""
Break of Structure (BOS) / Confirmed BOS (cBOS) detector.

Algorithm mirrors smc.py (github.com/joshyattridge/smart-money-concepts) §bos_choch().

Terminology:
- BOS  : break in the trend direction (continuation).
         Bullish: [low,high,low,high] with HL+HH — close above prior high B.
         Bearish: [high,low,high,low] with LH+LL  — close below prior low  B.
- cBOS : structural shift / Change of Character (CHoCH in smc).
         Bullish: [low,high,low,high] with LL+HH — reversal from bear to bull.
         Bearish: [high,low,high,low] with HH+LL — reversal from bull to bear.

Detection (per smc.py §bos_choch):
  For each 4-swing window [A,B,C,D] with the right alternating type pattern:
    1. Classify BOS or cBOS based on price relationships (same conditions as detect_market_structure).
    2. Level to break = B (the 2nd swing — prior extreme in the trend direction).
    3. Break bar = first bar AFTER C where close crosses B, up to and including D.
       Using boundary swings (see _add_boundary_swings) D may land at bar n-1, so the
       search naturally covers all remaining bars — equivalent to smc's "search to end".
    4. Only confirmed breaks (break bar found) are emitted as events.

Boundary swings (from _find_swings) are essential: the in-progress leg at the right
edge of the chart is never a confirmed swing, so without them the last window is
incomplete and no BOS fires on the current move.
"""

import numpy as np
import pandas as pd

from copilot.detectors.market_structure import _find_swings

TOOL_SCHEMA = {
    "name": "detect_bos",
    "description": (
        "Detect Break of Structure (BOS) and Confirmed BOS (cBOS) events on a given "
        "timeframe. Returns the most recent events newest-first with direction, broken "
        "level, and break-candle body size relative to ATR. "
        "BOS confirms trend continuation; cBOS signals a structural shift/reversal."
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


def _find_break_bar(closes, start: int, end: int, level: float, direction: str) -> int | None:
    """Return first index in [start..end] where close breaks level, or None."""
    end = min(end, len(closes) - 1)
    for i in range(start, end + 1):
        if direction == "above" and closes[i] > level:
            return i
        if direction == "below" and closes[i] < level:
            return i
    return None


def detect_bos(
    df: pd.DataFrame,
    swing_lookback: int = 5,
    max_results: int = 5,
) -> dict:
    min_bars = swing_lookback * 2 + 5
    if len(df) < min_bars:
        return {
            "status": "insufficient_data",
            "needed": min_bars,
            "got": len(df),
            "events": [],
            "count": 0,
            "latest_bias": "none",
        }

    opens_arr = df["open"].values
    closes_arr = df["close"].values
    tss = df.index

    atr_arr = (df["high"] - df["low"]).rolling(14).mean().values

    def _atr_at(i: int) -> float:
        v = atr_arr[i]
        if np.isnan(v):
            v = float(np.nanmean(atr_arr[: i + 1]))
        return v if v > 0 else 1.0

    # _find_swings = raw + dedup + boundary guards (mirrors smc.py §swing_highs_lows).
    # Boundary swings ensure the in-progress leg at the right edge is included in the
    # 4-swing window so BOS fires on the current move, not only on historical ones.
    swings = _find_swings(df, swing_lookback)

    if len(swings) < 4:
        return {"events": [], "count": 0, "latest_bias": "none"}

    events: list[dict] = []

    for w in range(len(swings) - 3):
        A, B, C, D = swings[w], swings[w + 1], swings[w + 2], swings[w + 3]
        types = [A["type"], B["type"], C["type"], D["type"]]

        # --- Bullish: [low, high, low, high] ---
        # Level to break = B (prior swing high).
        # BOS : C > A (HL) and D > B (HH) — continuation.
        # cBOS: C < A (LL) and D > B (HH) — reversal / Change of Character.
        if types == ["low", "high", "low", "high"]:
            level = B["price"]
            if D["price"] <= level:
                # D must exceed the prior high for there to be any break candidate.
                continue
            bos_type = "BOS" if C["price"] > A["price"] else "cBOS"
            # Search for first close above B in (C, D] — mirrors smc.py close_break logic.
            # D may be a synthetic boundary at bar n-1, so this naturally covers all
            # remaining bars (equivalent to smc's unbounded "search to end").
            break_idx = _find_break_bar(closes_arr, C["idx"] + 1, D["idx"], level, "above")
            if break_idx is None:
                continue
            body = abs(closes_arr[break_idx] - opens_arr[break_idx])
            atr_val = _atr_at(break_idx)
            events.append({
                "type": bos_type,
                "direction": "bullish",
                "broken_level": round(level, 2),
                "break_ts": tss[break_idx].isoformat(),
                "break_candle_body_atr": round(body / atr_val, 2),
            })

        # --- Bearish: [high, low, high, low] ---
        # Level to break = B (prior swing low).
        # BOS : C < A (LH) and D < B (LL) — continuation.
        # cBOS: C > A (HH) and D < B (LL) — reversal / Change of Character.
        elif types == ["high", "low", "high", "low"]:
            level = B["price"]
            if D["price"] >= level:
                continue
            bos_type = "BOS" if C["price"] < A["price"] else "cBOS"
            break_idx = _find_break_bar(closes_arr, C["idx"] + 1, D["idx"], level, "below")
            if break_idx is None:
                continue
            body = abs(closes_arr[break_idx] - opens_arr[break_idx])
            atr_val = _atr_at(break_idx)
            events.append({
                "type": bos_type,
                "direction": "bearish",
                "broken_level": round(level, 2),
                "break_ts": tss[break_idx].isoformat(),
                "break_candle_body_atr": round(body / atr_val, 2),
            })

    events_out = list(reversed(events))[:max_results]
    latest_bias = events[-1]["direction"] if events else "none"
    return {
        "events": events_out,
        "count": len(events_out),
        "latest_bias": latest_bias,
    }
