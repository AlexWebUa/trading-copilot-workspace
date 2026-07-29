"""
Shared utilities for OHLCV pattern detectors.

All functions are pure numpy/pandas operations — no side effects, no I/O.
Import via:
    from copilot.detectors.utils import (
        IMPULSE_ATR_THRESHOLD,
        calc_atr, extract_arrays,
        calc_ob_zone,
        is_bullish_ob, is_bearish_ob,
        find_sweep,
        detect_fvg_zone,
        is_zone_mitigated,
    )
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ── Threshold constants ───────────────────────────────────────────────────────

IMPULSE_ATR_THRESHOLD: float = 1.5
"""
Minimum impulse candle range relative to ATR(14) to qualify as a structural move.

A next-candle range below this threshold is classified as noise rather than
institutional intent.  Used identically by:
    order_block.py, breaker_block.py, mitigation_block.py, sponsored_candle.py
"""


# ── DataFrame helpers ─────────────────────────────────────────────────────────

def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    Return the unified true-range ATR at the most recent bar.

    Delegates to ``smc_lib.true_range_atr`` — the single ATR definition used
    across the package (true range = max of high−low, |high−prev_close|,
    |low−prev_close|), not the old high-low proxy.  Returns the last-bar scalar;
    use ``true_range_atr`` directly when a per-bar array is needed inside a loop.

    Parameters
    ----------
    df : pd.DataFrame
        Canonical OHLCV DataFrame.
    period : int
        Rolling window length.  Default 14.

    Returns
    -------
    float
        ATR at the most recent bar.
    """
    from copilot.detectors.smc_lib import true_range_atr

    return float(true_range_atr(df, period)[-1])


def extract_arrays(
    df: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, pd.Index]:
    """
    Extract the four OHLC price arrays and the timestamp index from a DataFrame.

    Returns zero-copy numpy views for fast element-wise access inside detector
    loops.  All four arrays and the index share the same length.

    Parameters
    ----------
    df : pd.DataFrame
        Canonical OHLCV DataFrame.

    Returns
    -------
    opens  : np.ndarray  — open prices
    highs  : np.ndarray  — high prices
    lows   : np.ndarray  — low prices
    closes : np.ndarray  — close prices
    tss    : pd.Index    — DatetimeIndex (UTC)
    """
    return (
        df["open"].values,
        df["high"].values,
        df["low"].values,
        df["close"].values,
        df.index,
    )


# ── OB zone geometry ──────────────────────────────────────────────────────────

def calc_ob_zone(
    highs: np.ndarray,
    lows: np.ndarray,
    i: int,
) -> tuple[float, float]:
    """
    Return the full candle range (high/low) at index ``i`` as the Order Block zone.

    Uses the full candle range including wicks, capturing the complete institutional
    footprint — the entire price range traded during the OB candle, not just the body.

    Parameters
    ----------
    highs : high price array
    lows  : low price array
    i     : candle index

    Returns
    -------
    (ob_high, ob_low) : tuple[float, float]
        ``ob_high = highs[i]``
        ``ob_low  = lows[i]``
    """
    return float(highs[i]), float(lows[i])


# ── Impulse / OB pattern predicates ──────────────────────────────────────────

def is_bullish_ob(
    closes: np.ndarray,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    i: int,
    atr: float,
    threshold: float = IMPULSE_ATR_THRESHOLD,
) -> bool:
    """
    Return ``True`` if candle ``i`` forms a bullish Order Block pattern.

    A bullish OB is a bearish (red) candle immediately followed by a bullish
    impulse that closes above the OB candle's high.  The impulse candle must
    also exceed ``threshold × ATR`` in range to filter out noise moves.

    Conditions
    ----------
    1. ``closes[i] < opens[i]``                        — OB candle is bearish
    2. ``closes[i+1] > highs[i]``                      — impulse closes above OB high
    3. ``(highs[i+1] - lows[i+1]) > threshold × atr`` — impulse range is significant

    Parameters
    ----------
    closes    : close price array
    opens     : open price array
    highs     : high price array
    lows      : low price array
    i         : index of the OB candidate candle; ``i+1`` is the impulse candle
    atr       : ATR(14) value at the current bar
    threshold : minimum impulse-to-ATR ratio (default ``IMPULSE_ATR_THRESHOLD``)
    """
    return (
        closes[i] < opens[i]
        and closes[i + 1] > highs[i]
        and (highs[i + 1] - lows[i + 1]) > threshold * atr
    )


def is_bearish_ob(
    closes: np.ndarray,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    i: int,
    atr: float,
    threshold: float = IMPULSE_ATR_THRESHOLD,
) -> bool:
    """
    Return ``True`` if candle ``i`` forms a bearish Order Block pattern.

    A bearish OB is a bullish (green) candle immediately followed by a bearish
    impulse that closes below the OB candle's low.  The impulse candle must
    also exceed ``threshold × ATR`` in range to filter out noise moves.

    Conditions
    ----------
    1. ``closes[i] > opens[i]``                        — OB candle is bullish
    2. ``closes[i+1] < lows[i]``                       — impulse closes below OB low
    3. ``(highs[i+1] - lows[i+1]) > threshold × atr`` — impulse range is significant

    Parameters
    ----------
    closes    : close price array
    opens     : open price array
    highs     : high price array  (required for impulse range: ``highs[i+1] - lows[i+1]``)
    lows      : low price array
    i         : index of the OB candidate candle; ``i+1`` is the impulse candle
    atr       : ATR(14) value at the current bar
    threshold : minimum impulse-to-ATR ratio (default ``IMPULSE_ATR_THRESHOLD``)
    """
    return (
        closes[i] > opens[i]
        and closes[i + 1] < lows[i]
        and (highs[i + 1] - lows[i + 1]) > threshold * atr
    )


# ── Liquidity sweep detection ─────────────────────────────────────────────────

def find_sweep(
    wicks: np.ndarray,
    closes: np.ndarray,
    level: float,
    side: str,
) -> tuple[bool, int]:
    """
    Find the first bar in a slice that sweeps ``level`` and closes back.

    A confirmed sweep requires two conditions on the same candle:
      * The wick (low or high) pierces the level.
      * The close returns to the "safe" side of the level.

    This function unifies two private helpers that existed separately:
      * ``_find_sweep`` in ``sponsored_candle.py``   — returned ``(bool, int)``
      * ``_has_sweep_of_level`` in ``mitigation_block.py`` — returned ``bool`` only

    Callers that only need the boolean can check the first element of the tuple.

    Parameters
    ----------
    wicks  : low prices when checking "sellside"; high prices for "buyside"
    closes : close price array (same length as ``wicks``)
    level  : the price level under test
    side   : ``"sellside"`` or ``"buyside"``

    Returns
    -------
    (found, index) : tuple[bool, int]
        ``found`` — ``True`` if a sweep bar was found.
        ``index`` — position within the passed slice, or ``-1`` if not found.

    Sweep conditions
    ----------------
    sellside : ``wicks[j] < level`` AND ``closes[j] > level``
    buyside  : ``wicks[j] > level`` AND ``closes[j] < level``
    """
    for j in range(len(wicks)):
        if side == "sellside":
            if wicks[j] < level and closes[j] > level:
                return True, j
        else:  # buyside
            if wicks[j] > level and closes[j] < level:
                return True, j
    return False, -1


# ── FVG pattern extraction ────────────────────────────────────────────────────

def detect_fvg_zone(
    highs: np.ndarray,
    lows: np.ndarray,
    i: int,
) -> tuple[float, float, str] | None:
    """
    Test whether the 3-candle window starting at ``i`` contains a Fair Value Gap.

    Candle roles:
      C0 = index ``i`` (pre-impulse candle)
      C1 = index ``i+1`` (impulse candle — not inspected directly)
      C2 = index ``i+2`` (post-impulse candle)

    The FVG is the *gap* left by C1's momentum — the price range that C1
    skipped over without trading.

    Patterns
    --------
    Bullish FVG: ``lows[i+2] > highs[i]``
        Gap between C0 top and C2 bottom.
        Returns ``(upper=lows[i+2], lower=highs[i], "bullish")``.

    Bearish FVG: ``highs[i+2] < lows[i]``
        Gap between C0 bottom and C2 top.
        Returns ``(upper=lows[i], lower=highs[i+2], "bearish")``.

    No pattern → returns ``None``.

    Parameters
    ----------
    highs : high price array
    lows  : low price array
    i     : index of C0; caller must ensure ``i + 2 < len(highs)``

    Returns
    -------
    ``(upper, lower, fvg_type)`` or ``None``
        ``upper`` and ``lower`` are the zone boundaries (``upper > lower``).
        ``fvg_type`` is the *original* gap type (``"bullish"`` or ``"bearish"``).
    """
    c0_high, c0_low = highs[i], lows[i]
    c2_high, c2_low = highs[i + 2], lows[i + 2]

    if c2_low > c0_high:
        return float(c2_low), float(c0_high), "bullish"
    if c2_high < c0_low:
        return float(c0_low), float(c2_high), "bearish"
    return None


# ── Zone mitigation check ─────────────────────────────────────────────────────

def is_zone_mitigated(
    zone_high: float,
    zone_low: float,
    future_prices: np.ndarray,
    direction: str,
) -> bool:
    """
    Return ``True`` if future price action has visited the zone's midpoint (50 %).

    "Mitigated" in ICT context means that enough of the institutional position
    has been filled that the zone no longer represents a pristine, untested POI.
    The 50 % (CE — Candle Equilibrium) threshold is the standard criterion.

    Parameters
    ----------
    zone_high     : upper boundary of the zone
    zone_low      : lower boundary of the zone
    future_prices : price array from after zone formation.
                    Pass *lows* for bullish zones (checking downward wicks into the zone).
                    Pass *highs* for bearish zones (checking upward wicks into the zone).
    direction     : ``"bullish"`` — zone acts as support; mitigated when
                    ``future_prices <= midpoint``.
                    ``"bearish"`` — zone acts as resistance; mitigated when
                    ``future_prices >= midpoint``.

    Returns
    -------
    bool
    """
    if len(future_prices) == 0:
        return False
    midpoint = (zone_high + zone_low) / 2
    if direction == "bullish":
        return bool((future_prices <= midpoint).any())
    else:
        return bool((future_prices >= midpoint).any())
