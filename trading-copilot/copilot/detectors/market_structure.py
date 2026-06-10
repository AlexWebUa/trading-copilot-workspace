"""
Market structure detector: tracks HH/HL (bullish) vs LH/LL (bearish) swing sequence.

Algorithm mirrors smc.py (github.com/joshyattridge/smart-money-concepts):
- swing_highs_lows(): centered rolling window + iterative deduplication to strict H/L/H/L
- bos_choch(): 4-swing sliding window [A,B,C,D]; BOS = trend-continuation, CHoCH = reversal

Key insight (smc.py §swing_highs_lows, final block):
  The in-progress move at the right edge of the chart is never a confirmed swing because
  it has no future bars to confirm it.  smc adds a *synthetic* boundary swing at the first
  and last bar using the bar's actual high/low so the current trend leg is always included
  in the window analysis.

State machine (last 4 alternating swings after boundary fix):
- Bullish: [low,high,low,high] with HL+HH (BOS) or LL+HH (cBOS structural shift)
- Bearish: [high,low,high,low] with LH+LL (BOS) or HH+LL (cBOS structural shift)
- Ranging: mixed or insufficient data.
"""

import numpy as np
import pandas as pd

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
    """
    Full swing pipeline: raw detection → deduplication → boundary guards.

    This is the canonical entry point for all detectors that need swing points.
    Do NOT call _find_raw_swings + _deduplicate_swings separately in new code;
    use this function to ensure boundary swings are always included.
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

    # raw_dedup: confirmed real swings only (no boundary) — used for last_h/last_l labels
    # and bars_in_state (distance from last *confirmed* swing to current bar).
    raw_dedup = _deduplicate_swings(_find_raw_swings(df, swing_lookback))

    # swings: with boundary guards — used for state-machine pattern matching.
    swings = _add_boundary_swings(raw_dedup, df)

    # Last confirmed (real) swing highs/lows for output labels
    last_h = next((s for s in reversed(raw_dedup) if s["type"] == "high"), None)
    last_l = next((s for s in reversed(raw_dedup) if s["type"] == "low"),  None)

    state = "ranging"
    last_bos_type = None

    if len(swings) >= 4:
        last4 = swings[-4:]
        types = [s["type"] for s in last4]
        A, B, C, D = [s["price"] for s in last4]

        # Bullish: [low, high, low, high]
        if types == ["low", "high", "low", "high"]:
            if C > A and D > B:          # HL + HH → trend continuation BOS
                state = "bullish"
                last_bos_type = "BOS"
            elif C < A and D > B:        # LL + HH → structural reversal cBOS
                state = "bullish"
                last_bos_type = "cBOS"

        # Bearish: [high, low, high, low]
        elif types == ["high", "low", "high", "low"]:
            if C < A and D < B:          # LH + LL → trend continuation BOS
                state = "bearish"
                last_bos_type = "BOS"
            elif C > A and D < B:        # HH + LL → structural reversal cBOS
                state = "bearish"
                last_bos_type = "cBOS"

    current_price = float(df["close"].iloc[-1])
    atr = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1])
    # bars_in_state: distance from last *confirmed* swing to now
    bars_in_state = len(df) - 1 - raw_dedup[-1]["idx"] if raw_dedup else 0

    return {
        "state": state,
        "last_swing_high": _fmt_swing(last_h, tss) if last_h else None,
        "last_swing_low":  _fmt_swing(last_l, tss) if last_l else None,
        "bars_in_state": bars_in_state,
        "current_price": round(current_price, 2),
        "atr_14": round(atr, 2),
        "last_bos_type": last_bos_type,
    }
