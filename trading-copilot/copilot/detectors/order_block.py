"""
Order Block (OB) detector — swing-break algorithm.

Algorithm mirrors smc.py (github.com/joshyattridge/smart-money-concepts) §ob().

An Order Block is the candle that represents institutional positioning immediately
before a move that breaks a prior structural swing level.

Formation logic (per smc.py):
  Bullish OB:
    1. A swing HIGH is confirmed at some bar S (requires `swing_lookback` bars on each side).
    2. At breakout bar B, close[B] > high[S]  — price closes above the swing high.
    3. OB candle = the bar with the LOWEST LOW in the window (S+1 .. B-1).
       That is the deepest retracement candle before the structural break —
       the most likely location of resting institutional buy orders.
    4. OB zone = (high[OB], low[OB]) — full candle range.

  Bearish OB: symmetric.
    1. Swing LOW confirmed at S.
    2. close[B] < low[S] — price closes below the swing low.
    3. OB candle = bar with the HIGHEST HIGH in window (S+1 .. B-1).
    4. OB zone = (high[OB], low[OB]).

Why this is different from the old 2-candle pattern:
  The old implementation used `is_bullish_ob` — a purely local predicate (bearish
  candle followed immediately by a large impulse).  That fires on any big up-move
  without needing a structural level to be broken, producing many low-quality OBs.
  The swing-break approach ensures every OB is anchored to a confirmed structural
  event, matching the "institutional footprint" concept in SMC/ICT.

Mitigation (unchanged from previous version, better than smc's boundary-touch):
  OB is mitigated when future lows (bullish) or highs (bearish) reach the 50 %
  midpoint (CE — Candle Equilibrium) of the zone, not just when price touches the
  edge.  This is more aligned with ICT methodology.

Quality marker:
  `has_fvg_after` — True if a Fair Value Gap exists in the 5 bars immediately after
  the OB candle.  FVG presence indicates impulsive departure from the OB, which ICT
  identifies as a higher-quality zone.
"""

import numpy as np
import pandas as pd

from copilot.detectors.utils import (
    calc_atr,
    calc_ob_zone,
    extract_arrays,
    is_zone_mitigated,
)
from copilot.detectors.fvg import detect_fvg

TOOL_SCHEMA = {
    "name": "detect_order_block",
    "description": (
        "Find active Order Blocks (demand/supply zones where institutions placed orders). "
        "Each OB is the deepest-retracement candle before a close that broke a confirmed "
        "structural swing high or low.  Use to identify high-probability POIs for entries."
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
                "description": "How many bars back to scan for breakout events",
            },
            "max_results":    {"type": "integer", "default": 6},
            "swing_lookback": {
                "type": "integer",
                "default": 5,
                "description": "Bars each side to confirm a structural swing pivot",
            },
        },
        "required": ["symbol", "timeframe"],
    },
}


def detect_order_block(
    df: pd.DataFrame,
    lookback: int = 100,
    max_results: int = 6,
    swing_lookback: int = 5,
) -> dict:
    """
    Detect Order Blocks using the swing-break algorithm from smc.py.

    Parameters
    ----------
    df            : canonical OHLCV DataFrame
    lookback      : how many recent bars to scan for breakout events (the breakout
                    bar must fall within the last `lookback` bars; the OB candle and
                    swing may be older)
    max_results   : cap on returned OBs (sorted: unmitigated first, then by recency)
    swing_lookback: bars each side to confirm a fractal swing pivot
    """
    if len(df) < 10:
        return {
            "status": "insufficient_data",
            "needed": 10,
            "got": len(df),
            "obs": [],
            "count": 0,
        }

    # ── Import swing helpers (internal, not detectors) ────────────────────────
    from copilot.detectors.market_structure import _find_raw_swings

    opens, highs, lows, closes, tss = extract_arrays(df)
    atr           = calc_atr(df)
    n             = len(df)
    current_price = float(closes[-1])

    # Confirmed RAW swings, consumed chronologically — NO deduplication.
    # P0-3 / root cause R1: alternation-dedup merges consecutive same-type
    # swings and can erase the very swing whose break defines the OB (e.g.
    # price breaks a swing high before a pullback low confirms — the broken
    # high would be deleted in favor of the newer, higher one). Verified
    # empirically that smc.ob inherits this flaw, so the swing-break scan
    # below runs on raw confirmed swings instead.
    raw_swings   = _find_raw_swings(df, swing_lookback)
    swing_highs  = [s for s in raw_swings if s["type"] == "high"]   # sorted by idx asc
    swing_lows   = [s for s in raw_swings if s["type"] == "low"]

    scan_start    = max(0, n - lookback)
    obs: list[dict] = []
    crossed_high: set[int] = set()   # swing-high indices already used as OB triggers
    crossed_low:  set[int] = set()

    # Pointer into each sorted swing list: first position with idx >= current bar i.
    # Advancing before the scan_start skip keeps pointers in sync for later bars.
    h_ptr = 0
    l_ptr = 0

    for i in range(n):
        # ── Advance pointers past swings that occurred before bar i ─────────
        while h_ptr < len(swing_highs) and swing_highs[h_ptr]["idx"] < i:
            h_ptr += 1
        while l_ptr < len(swing_lows) and swing_lows[l_ptr]["idx"] < i:
            l_ptr += 1

        if i < scan_start:
            continue   # outside lookback window — pointers are still maintained above

        # ── Bullish OB trigger: close breaks above most-recent uncrossed swing HIGH ──
        if h_ptr > 0:
            sh = swing_highs[h_ptr - 1]   # most recent swing high before bar i
            if sh["idx"] not in crossed_high and closes[i] > sh["price"]:
                crossed_high.add(sh["idx"])

                # OB candle = lowest-low bar in window (sh+1 .. i-1)
                win_s = sh["idx"] + 1
                win_e = i          # exclusive — don't include the breakout bar itself
                if win_e > win_s:
                    seg    = lows[win_s:win_e]
                    ob_idx = win_s + int(np.where(seg == seg.min())[0][-1])
                else:
                    ob_idx = max(0, i - 1)

                ob_h, ob_l = calc_ob_zone(highs, lows, ob_idx)
                obs.append({
                    "type":          "bullish",
                    "high":          round(ob_h, 2),
                    "low":           round(ob_l, 2),
                    "formed_ts":     tss[ob_idx].isoformat(),
                    "has_fvg_after": _check_fvg_after(df, ob_idx + 1, "bullish"),
                    # Mitigation: check lows AFTER the breakout bar (price "returning")
                    "is_mitigated":  is_zone_mitigated(ob_h, ob_l, lows[i + 1:], "bullish"),
                    "distance_atr":  round(abs(current_price - ob_l) / atr, 2) if atr else 0,
                    "age_bars":      n - 1 - ob_idx,
                })

        # ── Bearish OB trigger: close breaks below most-recent uncrossed swing LOW ──
        if l_ptr > 0:
            sl = swing_lows[l_ptr - 1]    # most recent swing low before bar i
            if sl["idx"] not in crossed_low and closes[i] < sl["price"]:
                crossed_low.add(sl["idx"])

                # OB candle = highest-high bar in window (sl+1 .. i-1)
                win_s = sl["idx"] + 1
                win_e = i
                if win_e > win_s:
                    seg    = highs[win_s:win_e]
                    ob_idx = win_s + int(np.where(seg == seg.max())[0][-1])
                else:
                    ob_idx = max(0, i - 1)

                ob_h, ob_l = calc_ob_zone(highs, lows, ob_idx)
                obs.append({
                    "type":          "bearish",
                    "high":          round(ob_h, 2),
                    "low":           round(ob_l, 2),
                    "formed_ts":     tss[ob_idx].isoformat(),
                    "has_fvg_after": _check_fvg_after(df, ob_idx + 1, "bearish"),
                    # Mitigation: check highs AFTER the breakout bar
                    "is_mitigated":  is_zone_mitigated(ob_h, ob_l, highs[i + 1:], "bearish"),
                    "distance_atr":  round(abs(current_price - ob_h) / atr, 2) if atr else 0,
                    "age_bars":      n - 1 - ob_idx,
                })

    # Sort: unmitigated first, then nearest (smallest age)
    obs.sort(key=lambda x: (x["is_mitigated"], x["age_bars"]))
    trimmed = obs[:max_results]
    return {"obs": trimmed, "count": len(trimmed)}


def _check_fvg_after(df: pd.DataFrame, start_idx: int, ob_type: str) -> bool:
    """
    Return True if a Fair Value Gap of matching direction exists in the 5 bars
    immediately following the OB candle.

    An FVG right after the OB indicates an impulsive departure from the zone —
    a quality marker in ICT: the institution left without trading back (gap = urgency).
    """
    end_idx = min(start_idx + 5, len(df))
    if end_idx - start_idx < 3:
        return False
    result = detect_fvg(df.iloc[start_idx:end_idx], max_age_bars=10)
    return any(f["type"] == ob_type for f in result.get("fvgs", []))
