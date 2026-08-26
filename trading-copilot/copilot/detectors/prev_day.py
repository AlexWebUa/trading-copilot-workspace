"""
Previous-day high / low — PDH & PDL.

The system talks about PDH/PDL everywhere (the analysis prompt cites them as
liquidity targets, the glossary defines them as key pools) but nothing produced
them: `detect_liquidity` only reports swing- and equal-high/low pools. A rule
that wants "the swept level is PDH or PDL" had no field to test.

Day boundary is a parameter, not an assumption. Binance daily candles roll at
00:00 UTC, while ICT material anchors the day at New York midnight — the two
disagree by 5 hours and produce different extremes. Default is UTC because that
is what the exchange's own D1 candle shows; pass `day_tz="America/New_York"`
for the ICT convention.

Only **completed** days are considered: the day in progress has no final high
or low, so using it would leak information that did not exist at the time.
"""

from __future__ import annotations

import pandas as pd

TOOL_SCHEMA = {
    "name": "detect_previous_day_levels",
    "description": (
        "Previous day's high and low (PDH / PDL) — the classic daily liquidity pools, "
        "plus whether price has already taken them. Reports how far price sits from each "
        "in ATR, so you can tell a pool that is in play from one that is far away. "
        "Use for daily-bias targets and to check whether a swept level was PDH/PDL "
        "rather than an ordinary swing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "e.g. BTCUSDT"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h"],
                "description": "Intraday timeframe to aggregate days from (not 1d).",
            },
            "day_tz": {
                "type": "string",
                "default": "UTC",
                "description": (
                    "Timezone whose midnight starts the day. 'UTC' matches Binance's "
                    "daily candle; 'America/New_York' matches the ICT convention."
                ),
            },
        },
        "required": ["symbol", "timeframe"],
    },
}


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    from copilot.detectors.smc_lib import true_range_atr

    series = true_range_atr(df, period)
    if len(series) == 0:
        return 0.0
    value = float(series[-1]) if hasattr(series, "__getitem__") else 0.0
    return value if value > 0 else 0.0


def detect_previous_day_levels(
    df: pd.DataFrame,
    day_tz: str = "UTC",
) -> dict:
    """PDH/PDL of the last completed day, with sweep state and distance in ATR."""
    if len(df) < 2:
        return {"status": "insufficient_data", "reason": "need at least 2 bars"}

    try:
        local_index = df.index.tz_convert(day_tz)
    except Exception:
        return {"status": "error", "reason": f"unknown timezone {day_tz!r}"}

    days = local_index.normalize()
    unique_days = days.unique()
    if len(unique_days) < 2:
        return {
            "status": "insufficient_data",
            "reason": "need bars from at least two calendar days",
        }

    # The last day in the frame is still forming — the previous one is the last
    # completed day, and its extremes are what the trader marks up.
    prev_day = unique_days[-2]
    mask = days == prev_day
    prev = df[mask]
    if prev.empty:
        return {"status": "insufficient_data", "reason": "previous day has no bars"}

    pdh = float(prev["high"].max())
    pdl = float(prev["low"].min())
    pdh_ts = prev.index[prev["high"].values.argmax()]
    pdl_ts = prev.index[prev["low"].values.argmin()]

    today = df[days == unique_days[-1]]
    current_price = float(df["close"].iloc[-1])
    atr = _atr(df)

    def _distance(level: float) -> float | None:
        if atr <= 0:
            return None
        return round(abs(current_price - level) / atr, 2)

    # "Swept" = wicked beyond and closed back; "broken" = closed through.
    pdh_swept = bool((today["high"] > pdh).any()) if not today.empty else False
    pdh_broken = bool((today["close"] > pdh).any()) if not today.empty else False
    pdl_swept = bool((today["low"] < pdl).any()) if not today.empty else False
    pdl_broken = bool((today["close"] < pdl).any()) if not today.empty else False

    return {
        "status": "ok",
        "day_tz": day_tz,
        "prev_day": str(prev_day.date()),
        "pdh": round(pdh, 2),
        "pdl": round(pdl, 2),
        "pdh_ts": pdh_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pdl_ts": pdl_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pdh_swept": pdh_swept and not pdh_broken,
        "pdh_broken": pdh_broken,
        "pdl_swept": pdl_swept and not pdl_broken,
        "pdl_broken": pdl_broken,
        "current_price": round(current_price, 2),
        "pdh_distance_atr": _distance(pdh),
        "pdl_distance_atr": _distance(pdl),
        "atr_14": round(atr, 2) if atr else None,
    }
