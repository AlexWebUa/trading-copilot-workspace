"""
Fair Value Gap (FVG) / Imbalance detector.

3-candle pattern:
  Bullish FVG: candle[2].low > candle[0].high  (gap between C0 top and C2 bottom)
  Bearish FVG: candle[2].high < candle[0].low  (gap between C0 bottom and C2 top)

The impulse candle is C1 (middle). FVG zone is the gap left by C1's momentum.

Fill states (per KB):
  untouched : price never entered the zone
  IOFED     : Inversion of FVG Entry Depth — wick touched ≥1% but not 50%
  CE_tagged  : Candle Equilibrium (50% of zone) tagged
  filled    : price closed fully through the zone

Active FVGs only (not fully filled). Ordered newest → oldest.
"""

import numpy as np
import pandas as pd

from copilot.detectors.utils import calc_atr, detect_fvg_zone, extract_arrays

TOOL_SCHEMA = {
    "name": "detect_fvg",
    "description": (
        "Find active Fair Value Gaps (3-candle imbalances) on a given timeframe. "
        "Returns unfilled or partially filled FVGs with fill state. "
        "Use when you need to identify unmitigated inefficiencies as POIs."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "e.g. BTCUSDT"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "min_width_atr": {
                "type": "number",
                "default": 0.1,
                "description": "Minimum FVG width as fraction of ATR(14)",
            },
            "max_age_bars": {
                "type": "integer",
                "default": 200,
                "description": "Ignore FVGs older than this many bars",
            },
            "max_results": {
                "type": "integer",
                "default": 8,
                "description": "Max FVGs to return",
            },
        },
        "required": ["symbol", "timeframe"],
    },
}


def detect_fvg(
    df: pd.DataFrame,
    min_width_atr: float = 0.1,
    max_age_bars: int = 200,
    max_results: int = 8,
) -> dict:
    if len(df) < 3:
        return {"status": "insufficient_data", "needed": 3, "got": len(df), "fvgs": [], "count_active": 0}

    atr = calc_atr(df)
    min_width = atr * min_width_atr

    opens, highs, lows, closes, tss = extract_arrays(df)

    active_fvgs: list[dict] = []
    start_i = max(0, len(df) - max_age_bars - 2)

    for i in range(start_i, len(df) - 2):
        zone = detect_fvg_zone(highs, lows, i)
        if zone is None:
            continue
        upper, lower, fvg_type = zone

        width = upper - lower
        if width < min_width:
            continue

        # Measure fill by subsequent price action
        future_highs = highs[i + 3 :]
        future_lows = lows[i + 3 :]
        age_bars = len(df) - 1 - (i + 2)

        fill_pct, fill_state = _fill_state(fvg_type, upper, lower, future_highs, future_lows)

        if fill_state == "filled":
            continue  # fully mitigated, skip

        active_fvgs.append({
            "type": fvg_type,
            "upper": round(upper, 2),
            "lower": round(lower, 2),
            "formed_ts": tss[i + 1].isoformat(),  # impulse candle timestamp
            "fill_percentage": round(fill_pct, 1),
            "fill_state": fill_state,
            "age_bars": age_bars,
            "width_atr_fraction": round(width / atr, 3) if atr else 0,
        })

    # Newest first
    active_fvgs.sort(key=lambda x: x["age_bars"])
    trimmed = active_fvgs[:max_results]

    return {"fvgs": trimmed, "count_active": len(trimmed)}


def _fill_state(
    fvg_type: str,
    upper: float,
    lower: float,
    future_highs: "np.ndarray",
    future_lows: "np.ndarray",
) -> tuple[float, str]:
    width = upper - lower
    if width == 0:
        return 0.0, "filled"

    if fvg_type == "bullish":
        # Price retraces downward into the gap
        min_low = float(future_lows.min()) if len(future_lows) else upper
        if min_low <= lower:
            return 100.0, "filled"
        penetration = max(0.0, upper - min_low)
    else:
        # Price retraces upward into the gap
        max_high = float(future_highs.max()) if len(future_highs) else lower
        if max_high >= upper:
            return 100.0, "filled"
        penetration = max(0.0, max_high - lower)

    pct = (penetration / width) * 100.0

    if pct >= 50:
        return pct, "CE_tagged"
    if pct >= 1:
        return pct, "IOFED"
    return 0.0, "untouched"
