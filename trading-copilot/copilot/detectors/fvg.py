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

Consecutive FVG merging (join_consecutive=True, default):
  When a multi-candle impulse leaves back-to-back 3-candle gaps, each window
  produces a separate FVG.  Treating them as independent POIs overstates
  resolution — a single sweep of the area takes them all out together.
  Merging produces one zone per impulse, matching smc.py fvg(join_consecutive=True).

  Two FVGs merge if they are same-direction and adjacent (bar_idx differs by 1,
  meaning their 3-candle windows share bars C1/C2 of the earlier and C0/C1 of
  the later).  The merged zone takes the widest boundaries (max upper, min lower).
  Fill state is recalculated against future bars after the last C2 in the chain.

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
            "join_consecutive": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Merge adjacent same-direction FVGs into one zone. "
                    "Matches smc.py fvg(join_consecutive=True). "
                    "Reduces noise from multi-candle impulses that leave several "
                    "overlapping 3-candle gaps."
                ),
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
    join_consecutive: bool = True,
) -> dict:
    if len(df) < 3:
        return {"status": "insufficient_data", "needed": 3, "got": len(df), "fvgs": [], "count_active": 0}

    atr = calc_atr(df)
    min_width = atr * min_width_atr

    opens, highs, lows, closes, tss = extract_arrays(df)
    n = len(df)

    active_fvgs: list[dict] = []
    start_i = max(0, n - max_age_bars - 2)

    for i in range(start_i, n - 2):
        zone = detect_fvg_zone(highs, lows, i)
        if zone is None:
            continue
        upper, lower, fvg_type = zone

        width = upper - lower
        if width < min_width:
            continue

        # Fill measured against all bars after C2
        future_highs = highs[i + 3:]
        future_lows  = lows[i + 3:]
        age_bars      = n - 1 - (i + 2)

        fill_pct, fill_state = _fill_state(fvg_type, upper, lower, future_highs, future_lows)

        if fill_state == "filled":
            continue

        active_fvgs.append({
            "type":              fvg_type,
            "upper":             round(upper, 2),
            "lower":             round(lower, 2),
            "formed_ts":         tss[i + 1].isoformat(),   # C1 impulse timestamp
            "fill_percentage":   round(fill_pct, 1),
            "fill_state":        fill_state,
            "age_bars":          age_bars,
            "width_atr_fraction": round(width / atr, 3) if atr else 0,
            "_bar_idx":          i,    # internal — used by _join_consecutive_fvgs, removed before output
        })

    # ── Consecutive FVG merging ───────────────────────────────────────────────
    if join_consecutive and len(active_fvgs) > 1:
        active_fvgs = _join_consecutive_fvgs(active_fvgs, highs, lows, n, atr)

    # Newest first, cap results
    active_fvgs.sort(key=lambda x: x["age_bars"])
    trimmed = active_fvgs[:max_results]

    # Strip internal field from output
    for fvg in trimmed:
        fvg.pop("_bar_idx", None)

    return {"fvgs": trimmed, "count_active": len(trimmed)}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fill_state(
    fvg_type: str,
    upper: float,
    lower: float,
    future_highs: np.ndarray,
    future_lows: np.ndarray,
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


def _join_consecutive_fvgs(
    fvgs: list[dict],
    highs: np.ndarray,
    lows: np.ndarray,
    n: int,
    atr: float,
) -> list[dict]:
    """
    Merge chains of adjacent same-direction FVGs, matching smc.py join_consecutive.

    Two FVGs are "adjacent" when their C0 bar indices differ by exactly 1:
      FVG_A window = [k, k+1, k+2]
      FVG_B window = [k+1, k+2, k+3]   ← shares C1/C2 of A with C0/C1 of B

    The merge is done in a single forward pass; a chain A→B→C→D collapses
    iteratively: (A∪B)→C→D → (A∪B∪C)→D → A∪B∪C∪D.

    Merged zone:
      upper    = max across all individual uppers
      lower    = min across all individual lowers
      formed_ts = earliest (kept from first FVG in chain — C1 of that window)
      fill_state = recalculated from future bars after the LAST C2 in the chain
      age_bars   = distance from last C2 to current bar (merged zone is "as new"
                   as the most recent impulse in the chain)
    """
    result: list[dict] = []
    i = 0
    while i < len(fvgs):
        current = dict(fvgs[i])          # copy — do not mutate the original list
        last_bar_idx = current["_bar_idx"]

        j = i + 1
        while (j < len(fvgs)
               and fvgs[j]["type"] == current["type"]
               and fvgs[j]["_bar_idx"] == last_bar_idx + 1):
            # Expand zone to widest combined boundaries
            current["upper"] = max(current["upper"], fvgs[j]["upper"])
            current["lower"] = min(current["lower"], fvgs[j]["lower"])
            last_bar_idx = fvgs[j]["_bar_idx"]
            j += 1

        # Store the final bar_idx of the chain (used for future-slice calculation)
        current["_bar_idx"] = last_bar_idx

        # Recalculate fill state from after the last C2 in the merged chain
        future_start  = last_bar_idx + 3
        future_highs  = highs[future_start:]   # empty slice if future_start >= n
        future_lows   = lows[future_start:]

        fill_pct, fill_state = _fill_state(
            current["type"], current["upper"], current["lower"],
            future_highs, future_lows,
        )

        if fill_state != "filled":
            width = current["upper"] - current["lower"]
            current["fill_percentage"]    = round(fill_pct, 1)
            current["fill_state"]         = fill_state
            current["age_bars"]           = n - 1 - (last_bar_idx + 2)
            current["width_atr_fraction"] = round(width / atr, 3) if atr else 0
            result.append(current)

        i = j

    return result
