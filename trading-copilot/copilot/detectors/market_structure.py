"""
Market structure detector — thin wrapper over `smartmoneyconcepts` (P0-3).

State = direction of the most recent CONFIRMED structure event from
smc.bos_choch (close-break only). This fixes the June 2026 audit findings:
  - an HH/HL uptrend in a normal pullback stays "bullish" (no event has
    flipped it) instead of reading "ranging";
  - a wick dip cannot flip state — only a candle CLOSE through a
    structural level produces an event (R2 eliminated).

The legacy swing helpers (_find_raw_swings & co.) are kept below: the
order-block detector and debug tooling consume raw confirmed swings
chronologically (Working Rules: dedup must never erase a broken swing).
detect_market_structure itself no longer uses them.
"""

import numpy as np
import pandas as pd

from copilot.detectors.smc_lib import (
    confirmed_swings,
    lib_swings,
    structure_events,
    true_range_atr,
)

TOOL_SCHEMA = {
    "name": "detect_market_structure",
    "description": (
        "Determine the current market structure state (bullish/bearish/ranging) "
        "and identify the last significant swing high and swing low. "
        "Use at the start of any analysis to establish directional bias on a timeframe."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "swing_lookback": {
                "type": "integer",
                "default": 5,
                "description": "Bars each side to confirm a swing pivot",
            },
        },
        "required": ["symbol", "timeframe"],
    },
}


def _find_raw_swings(df: pd.DataFrame, lookback: int) -> list[dict]:
    """
    Return list of raw (not yet deduplicated) swing points {"type","price","idx"}.

    A swing high at bar i: high[i] is the maximum of the window [i-lookback, i+lookback].
    A swing low  at bar i: low[i]  is the minimum of the same window.
    Vectorized via sliding_window_view — no Python per-bar loop.
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(highs)
    win = 2 * lookback + 1

    if n < win:
        return []

    roll_max_h = np.lib.stride_tricks.sliding_window_view(highs, win).max(axis=1)
    roll_min_l = np.lib.stride_tricks.sliding_window_view(lows, win).min(axis=1)

    swings: list[dict] = []
    for offset in range(len(roll_max_h)):
        i = offset + lookback
        if highs[i] == roll_max_h[offset]:
            swings.append({"type": "high", "price": float(highs[i]), "idx": i})
        if lows[i] == roll_min_l[offset]:
            swings.append({"type": "low", "price": float(lows[i]), "idx": i})

    swings.sort(key=lambda x: x["idx"])
    return swings


def _deduplicate_swings(swings: list[dict]) -> list[dict]:
    """
    Enforce strict high-low-high-low alternation, keeping the most extreme point of each
    consecutive same-type run.

    Mirrors smc.py's iterative while-True deduplication loop which resolves groups of
    consecutive highs/lows in one pass until the sequence is fully alternating.
    """
    if not swings:
        return []
    result = [swings[0]]
    for s in swings[1:]:
        last = result[-1]
        if s["type"] == last["type"]:
            # Same type: keep the more extreme of the two
            if s["type"] == "high" and s["price"] >= last["price"]:
                result[-1] = s
            elif s["type"] == "low" and s["price"] <= last["price"]:
                result[-1] = s
        else:
            result.append(s)
    return result


def _add_boundary_swings(swings: list[dict], df: pd.DataFrame) -> list[dict]:
    """
    Add synthetic boundary swings at bar 0 and bar len(df)-1 — exactly as smc.py does.

    Rationale (from smc.py §swing_highs_lows final block):
      The current in-progress move on the right edge is not a confirmed swing because
      it lacks the future bars required for confirmation.  By planting a synthetic swing
      of the *opposite* type at the last bar (using that bar's actual high or low), the
      4-swing analysis window captures the live trend leg.  The same logic applies at the
      beginning of the series so the first window is well-formed.

    Rules (symmetric with smc):
      - First real swing is HIGH → prepend synthetic LOW at idx=0  (price = low[0])
      - First real swing is LOW  → prepend synthetic HIGH at idx=0  (price = high[0])
      - Last  real swing is LOW  → append  synthetic HIGH at idx=n-1 (price = high[-1])
      - Last  real swing is HIGH → append  synthetic LOW  at idx=n-1 (price = low[-1])

    Boundary positions (0 and n-1) are always different from the first/last real swing
    index because confirmed swings need at least `lookback` bars of context on each side.
    """
    if not swings:
        return swings

    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    result = list(swings)

    # --- beginning boundary ---
    first = result[0]
    if first["idx"] > 0:
        if first["type"] == "high":
            result.insert(0, {"type": "low",  "price": float(lows[0]),   "idx": 0})
        else:
            result.insert(0, {"type": "high", "price": float(highs[0]),  "idx": 0})

    # --- end boundary ---
    last = result[-1]
    if last["idx"] < n - 1:
        if last["type"] == "low":
            result.append({"type": "high", "price": float(highs[n - 1]), "idx": n - 1})
        else:
            result.append({"type": "low",  "price": float(lows[n - 1]),  "idx": n - 1})

    return result


def _find_swings(df: pd.DataFrame, lookback: int) -> list[dict]:
    """LEGACY (pre P0-3): raw detection → deduplication → boundary guards.

    Kept only for debug tooling. New detector code uses smc_lib for
    structure (lib_swings/structure_events) or _find_raw_swings directly
    when broken swings must survive (order blocks, R1).
    """
    return _add_boundary_swings(_deduplicate_swings(_find_raw_swings(df, lookback)), df)


def _fmt_swing(s: dict, tss) -> dict:
    return {
        "price": round(s["price"], 2),
        "ts": tss[s["idx"]].isoformat(),
    }


def detect_market_structure(df: pd.DataFrame, swing_lookback: int = 5) -> dict:
    min_bars = swing_lookback * 2 + 3
    if len(df) < min_bars:
        return {
            "status": "insufficient_data",
            "needed": min_bars,
            "got": len(df),
        }

    tss = df.index
    shl = lib_swings(df, swing_lookback)
    swings = confirmed_swings(shl, df)
    events = structure_events(df, shl)

    last_h = next((s for s in reversed(swings) if s["type"] == "high"), None)
    last_l = next((s for s in reversed(swings) if s["type"] == "low"), None)

    if events:
        latest = events[-1]
        state = latest["direction"]
        last_bos_type = latest["type"]
        # State began when the break candle CLOSED through the level
        bars_in_state = len(df) - 1 - latest["break_idx"]
    else:
        state = "ranging"
        last_bos_type = None
        bars_in_state = len(df) - 1 - swings[-1]["idx"] if swings else 0

    current_price = float(df["close"].iloc[-1])
    atr = float(true_range_atr(df)[-1])

    return {
        "state": state,
        "last_swing_high": _fmt_swing(last_h, tss) if last_h else None,
        "last_swing_low":  _fmt_swing(last_l, tss) if last_l else None,
        "bars_in_state": bars_in_state,
        "current_price": round(current_price, 2),
        "atr_14": round(atr, 2),
        "last_bos_type": last_bos_type,
    }
