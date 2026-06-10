"""
Adapter over the `smartmoneyconcepts` library (P0-3, June 2026).

The library is the algorithmic ground truth for swings and BOS/CHoCH
(Working Rules, knowledge hierarchy #1). This module:

  - imports it safely (its __init__ prints an emoji banner that crashes
    on cp1251 consoles — stdout is redirected during import);
  - converts its positional (RangeIndex) output into the swing-dict shape
    the detectors use;
  - provides the unified true-range ATR used by the rewritten detectors.

Known library limitation (verified empirically, probes/probe_smc_lib.py):
`smc.ob` consumes deduplicated swings, so a swing high that is broken
before an intervening swing low confirms gets erased and the OB is missed
(root cause R1). detect_order_block therefore keeps the swing-break
algorithm over RAW confirmed swings instead of wrapping `smc.ob`.
"""

from __future__ import annotations

import contextlib
import io

import numpy as np
import pandas as pd

with contextlib.redirect_stdout(io.StringIO()):
    from smartmoneyconcepts import smc

__all__ = ["smc", "lib_swings", "confirmed_swings", "structure_events", "true_range_atr"]


def lib_swings(df: pd.DataFrame, swing_lookback: int) -> pd.DataFrame:
    """smc.swing_highs_lows with our lookback convention.

    The library's swing_length is the bars checked around the candidate
    (it internally doubles the window). Returns the raw library frame
    (HighLow: 1/-1, Level) on a RangeIndex aligned to df positions.
    """
    return smc.swing_highs_lows(df, swing_length=swing_lookback)


def confirmed_swings(shl: pd.DataFrame, df: pd.DataFrame) -> list[dict]:
    """Library swings as [{"type", "price", "idx"}], confirmed only.

    The library plants synthetic opposite-type swings at positions 0 and
    n-1 so its own 4-swing windows cover the live leg. Those are not
    confirmed structure — a real swing needs lookback bars on both sides,
    so positions 0 and n-1 can never hold one. They are excluded here
    (root cause R2: reporting the right-edge synthetic swing made state
    wick-driven).
    """
    hl = shl["HighLow"].values
    lv = shl["Level"].values
    n = len(df)
    out: list[dict] = []
    for i in range(n):
        if np.isnan(hl[i]) or i == 0 or i == n - 1:
            continue
        out.append({
            "type": "high" if hl[i] == 1 else "low",
            "price": float(lv[i]),
            "idx": i,
        })
    return out


def structure_events(df: pd.DataFrame, shl: pd.DataFrame) -> list[dict]:
    """Confirmed BOS/CHoCH events from smc.bos_choch, oldest-first.

    Each event: {"type": "BOS"|"cBOS", "direction": "bullish"|"bearish",
    "level": float, "swing_idx": int, "break_idx": int}.
    Only events whose level was actually broken by a candle CLOSE are
    returned (the library drops unconfirmed ones).
    """
    ev = smc.bos_choch(df, shl, close_break=True)
    bos = ev["BOS"].values
    choch = ev["CHOCH"].values
    level = ev["Level"].values
    broken = ev["BrokenIndex"].values

    events: list[dict] = []
    for i in range(len(df)):
        if not np.isnan(bos[i]):
            sign = bos[i]
            ev_type = "BOS"
        elif not np.isnan(choch[i]):
            sign = choch[i]
            ev_type = "cBOS"  # CHoCH in smc terms
        else:
            continue
        if np.isnan(broken[i]):
            continue
        events.append({
            "type": ev_type,
            "direction": "bullish" if sign == 1 else "bearish",
            "level": float(level[i]),
            "swing_idx": i,
            "break_idx": int(broken[i]),
        })

    events.sort(key=lambda e: e["break_idx"])
    return events


def true_range_atr(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    """Per-bar true-range ATR array (unified ATR definition).

    Index per bar — never collapse to a scalar inside historical loops.
    """
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean().values
