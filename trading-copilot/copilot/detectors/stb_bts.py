"""
STB / BTS — the candle run that built the extreme.

The trader's definition for 30mOF (2026-08-26), which is narrower than the
knowledge-base note (`09_Setups/STB_BTS.md` describes a range from BOS to the
nearest extreme):

  STB (Sell to Buy)  the LAST CONSECUTIVE BEARISH candles that form the low,
                     wicks included. A demand zone — the long POI.
  BTS (Buy to Sell)  the last consecutive BULLISH candles that form the high,
                     wicks included. A supply zone — the short POI.

"Wicks included" is the load-bearing part: the zone spans the full high-to-low
range of the run, not its bodies. A body-only zone would sit inside the wick and
price would fill it far less often, which changes the trade count rather than
just the fill price.

The extremes are the same 3-candle fractals the order-flow walk uses, so a zone
here lines up with the structure the setup is built on — `swing_lookback=1` is
the setup's own setting, not a default worth changing casually.
"""

import pandas as pd

TOOL_SCHEMA = {
    "name": "detect_stb_bts",
    "description": (
        "Find STB (Sell to Buy) demand zones and BTS (Buy to Sell) supply zones: the "
        "run of consecutive same-colour candles that produced a swing low or swing "
        "high, wicks included. Use as an entry POI in the direction of the structure."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"],
            },
            "swing_lookback": {
                "type": "integer",
                "default": 1,
                "description": "Bars each side of the pivot. 1 = 3-candle, the setup's own.",
            },
            "max_results": {"type": "integer", "default": 6},
        },
        "required": ["symbol", "timeframe"],
    },
}


def _run_bounds(opens, closes, highs, lows, pivot: int, bearish: bool) -> tuple[int, int]:
    """Extend from the pivot back through candles of the same colour.

    The pivot itself may be the opposite colour — a low is often printed by a
    down candle that closes green after the reversal. In that case the run is
    just the pivot bar, which is still the zone that produced the extreme.
    """
    def same_colour(i: int) -> bool:
        return closes[i] < opens[i] if bearish else closes[i] > opens[i]

    start = pivot
    while start - 1 >= 0 and same_colour(start - 1):
        start -= 1
    return start, pivot


def detect_stb_bts(
    df: pd.DataFrame,
    swing_lookback: int = 1,
    max_results: int = 6,
) -> dict:
    n = len(df)
    k = swing_lookback
    if n < 3 * k + 2:
        return {"status": "insufficient_data", "needed": 3 * k + 2, "got": n,
                "stb": [], "bts": [], "count_active": 0}

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    tss = [ts.strftime("%Y-%m-%dT%H:%M:%SZ") for ts in df.index]

    stb: list[dict] = []
    bts: list[dict] = []

    for i in range(k, n - k):
        is_fl = all(lows[i] < lows[i - d] and lows[i] < lows[i + d] for d in range(1, k + 1))
        is_fh = all(highs[i] > highs[i - d] and highs[i] > highs[i + d] for d in range(1, k + 1))

        if is_fl:
            a, b = _run_bounds(opens, closes, highs, lows, i, bearish=True)
            zone_low = float(min(lows[a:b + 1]))
            zone_high = float(max(highs[a:b + 1]))
            # Mitigated once price has traded back above the zone's top after it
            # formed — the demand it holds has been used.
            after = highs[b + 1:]
            stb.append({
                "type": "bullish",
                "upper": round(zone_high, 2),
                "lower": round(zone_low, 2),
                "formed_ts": tss[i],
                "run_bars": b - a + 1,
                "is_mitigated": bool(len(after) and after.max() > zone_high),
                "age_bars": n - 1 - i,
            })

        if is_fh:
            a, b = _run_bounds(opens, closes, highs, lows, i, bearish=False)
            zone_low = float(min(lows[a:b + 1]))
            zone_high = float(max(highs[a:b + 1]))
            after = lows[b + 1:]
            bts.append({
                "type": "bearish",
                "upper": round(zone_high, 2),
                "lower": round(zone_low, 2),
                "formed_ts": tss[i],
                "run_bars": b - a + 1,
                "is_mitigated": bool(len(after) and after.min() < zone_low),
                "age_bars": n - 1 - i,
            })

    stb.sort(key=lambda z: z["age_bars"])
    bts.sort(key=lambda z: z["age_bars"])
    return {
        "stb": stb[:max_results],
        "bts": bts[:max_results],
        "count_active": sum(1 for z in stb + bts if not z["is_mitigated"]),
    }
