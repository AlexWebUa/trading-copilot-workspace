"""
Break of Structure (BOS) / Confirmed BOS (cBOS) detector — thin wrapper
over `smartmoneyconcepts` smc.bos_choch (P0-3, June 2026).

Terminology:
- BOS  : break in the trend direction (continuation).
- cBOS : structural shift / Change of Character (CHoCH in smc terms).

The library scans 4-swing windows over its own swing detection and emits
an event only when a candle CLOSE actually breaks the level (close_break).
Unconfirmed setups are dropped — there is no wick-driven or right-edge
synthetic event (June audit root causes R1/R2 for the old implementation).

Verified empirically against the June 2026 probe fixtures: the textbook
bullish BOS (close above prior swing high after a higher low) is emitted
at the correct level, and a flat market produces no events.
"""

import numpy as np
import pandas as pd

from copilot.detectors.smc_lib import lib_swings, structure_events, true_range_atr

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

    shl = lib_swings(df, swing_lookback)
    raw_events = structure_events(df, shl)  # oldest-first by break_idx

    if not raw_events:
        return {"events": [], "count": 0, "latest_bias": "none"}

    opens_arr = df["open"].values
    closes_arr = df["close"].values
    atr_arr = true_range_atr(df)
    tss = df.index

    events: list[dict] = []
    for ev in raw_events:
        j = ev["break_idx"]
        body = abs(closes_arr[j] - opens_arr[j])
        atr_val = float(atr_arr[j]) if atr_arr[j] > 0 else 1.0
        events.append({
            "type": ev["type"],
            "direction": ev["direction"],
            "broken_level": round(ev["level"], 2),
            "break_ts": tss[j].isoformat(),
            "break_candle_body_atr": round(body / atr_val, 2),
        })

    events_out = list(reversed(events))[:max_results]  # newest-first
    latest_bias = events[-1]["direction"]
    return {
        "events": events_out,
        "count": len(events_out),
        "latest_bias": latest_bias,
    }
