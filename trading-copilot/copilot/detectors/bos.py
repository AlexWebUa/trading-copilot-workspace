"""
Break of Structure (BOS) / Market Structure Shift (MSS) detector.

Terminology (per KB):
- BOS  : break in the trend direction (continuation); new HH in bull trend or LL in bear trend.
- cBOS : confirmed BOS — displacement candle whose body exceeds 1.5 × ATR(14).
- MSS  : break AGAINST the current bias (structure shift / reversal signal).

Detection rule: candle CLOSE must breach the prior swing extreme (not just a wick).

Algorithm: scan swings FORWARD, maintaining a rolling reference to the most recent
confirmed swing high and swing low.  At each bar we check whether the close crosses
the current reference; bias updates on every confirmed break so later breaks are
correctly classified as BOS (with trend) or MSS (against trend).
"""

import pandas as pd

from copilot.detectors.market_structure import _find_swings

TOOL_SCHEMA = {
    "name": "detect_bos",
    "description": (
        "Detect Break of Structure (BOS), Confirmed BOS (cBOS), and Market Structure Shift (MSS) "
        "events on a given timeframe.  Returns the most recent events newest-first with direction, "
        "broken level, and break-candle body size relative to ATR. "
        "BOS confirms trend continuation; cBOS adds displacement confirmation; "
        "MSS signals a potential trend reversal."
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

    opens_arr = df["open"].values
    closes_arr = df["close"].values
    tss = df.index
    atr = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1])

    all_swings = _find_swings(df, swing_lookback)
    if not all_swings:
        return {"events": [], "count": 0, "latest_bias": "none"}

    # Enrich each swing with its integer bar position so we can compare to loop index.
    # _find_swings stores timestamps as str(pd.Timestamp); build a reverse map.
    ts_to_pos = {str(ts): pos for pos, ts in enumerate(tss)}
    for s in all_swings:
        s["idx"] = ts_to_pos.get(s["ts"], -1)

    swing_highs = sorted(
        [s for s in all_swings if s["type"] == "high" and s["idx"] >= 0],
        key=lambda s: s["idx"],
    )
    swing_lows = sorted(
        [s for s in all_swings if s["type"] == "low" and s["idx"] >= 0],
        key=lambda s: s["idx"],
    )

    if not swing_highs and not swing_lows:
        return {"events": [], "count": 0, "latest_bias": "none"}

    events: list[dict] = []
    current_bias: str = "none"

    # Pointers into swing_highs / swing_lows: -1 = no swing seen yet.
    h_ptr: int = -1
    l_ptr: int = -1
    # Remember which pointer value we last broke to avoid re-detecting the same swing.
    broken_h_ptr: int | None = None
    broken_l_ptr: int | None = None

    scan_start = swing_lookback * 2

    for i in range(scan_start, len(df)):
        # Advance to the last confirmed swing high/low with idx < i.
        while h_ptr + 1 < len(swing_highs) and swing_highs[h_ptr + 1]["idx"] < i:
            h_ptr += 1
        while l_ptr + 1 < len(swing_lows) and swing_lows[l_ptr + 1]["idx"] < i:
            l_ptr += 1

        ref_h = swing_highs[h_ptr] if h_ptr >= 0 else None
        ref_l = swing_lows[l_ptr] if l_ptr >= 0 else None

        c = closes_arr[i]
        body = abs(closes_arr[i] - opens_arr[i])
        ts = tss[i]

        # ── Bullish break: close above the current reference swing high ──
        if ref_h is not None and c > ref_h["price"] and h_ptr != broken_h_ptr:
            bos_type = "MSS" if current_bias == "bearish" else "BOS"
            if bos_type == "BOS" and body > 1.5 * atr:
                bos_type = "cBOS"
            events.append({
                "type": bos_type,
                "direction": "bullish",
                "broken_level": round(ref_h["price"], 2),
                "break_ts": ts.isoformat(),
                "break_candle_body_atr": round(body / atr, 2) if atr else 0,
            })
            current_bias = "bullish"
            broken_h_ptr = h_ptr

        # ── Bearish break: close below the current reference swing low ──
        elif ref_l is not None and c < ref_l["price"] and l_ptr != broken_l_ptr:
            bos_type = "MSS" if current_bias == "bullish" else "BOS"
            if bos_type == "BOS" and body > 1.5 * atr:
                bos_type = "cBOS"
            events.append({
                "type": bos_type,
                "direction": "bearish",
                "broken_level": round(ref_l["price"], 2),
                "break_ts": ts.isoformat(),
                "break_candle_body_atr": round(body / atr, 2) if atr else 0,
            })
            current_bias = "bearish"
            broken_l_ptr = l_ptr

    events_out = list(reversed(events))[:max_results]
    return {
        "events": events_out,
        "count": len(events_out),
        "latest_bias": current_bias,
    }
