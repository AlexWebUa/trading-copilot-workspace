"""
Market structure detector: tracks HH/HL (bullish) vs LH/LL (bearish) swing sequence.

State machine:
- Build fractal swing points from the series.
- Bullish: last two swings are HH + HL (each higher than previous).
- Bearish: last two swings are LH + LL (each lower than previous).
- Ranging: mixed or insufficient data.

Swing "strength": strong if the swing was followed by a BOS of the prior level;
weak if it reversed before clearing the prior extreme.
"""

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


def _find_swings(df: pd.DataFrame, lookback: int) -> list[dict]:
    """Return sorted list of swing points with type/price/ts."""
    highs = df["high"].values
    lows = df["low"].values
    tss = df.index
    swings: list[dict] = []

    for i in range(lookback, len(df) - lookback):
        window_h = highs[i - lookback : i + lookback + 1]
        window_l = lows[i - lookback : i + lookback + 1]
        if highs[i] == window_h.max():
            swings.append({"type": "high", "price": float(highs[i]), "ts": tss[i]})
        elif lows[i] == window_l.min():
            swings.append({"type": "low", "price": float(lows[i]), "ts": tss[i]})

    swings.sort(key=lambda x: x["ts"])
    return swings


def detect_market_structure(df: pd.DataFrame, swing_lookback: int = 5) -> dict:
    min_bars = swing_lookback * 2 + 3
    if len(df) < min_bars:
        return {
            "status": "insufficient_data",
            "needed": min_bars,
            "got": len(df),
        }

    swings = _find_swings(df, swing_lookback)
    highs = [s for s in swings if s["type"] == "high"]
    lows = [s for s in swings if s["type"] == "low"]

    if len(highs) < 2 or len(lows) < 2:
        return {
            "state": "ranging",
            "last_swing_high": _fmt_swing(highs[-1], "weak") if highs else None,
            "last_swing_low": _fmt_swing(lows[-1], "weak") if lows else None,
            "bars_in_state": 0,
        }

    last_h, prev_h = highs[-1], highs[-2]
    last_l, prev_l = lows[-1], lows[-2]

    bullish = last_h["price"] > prev_h["price"] and last_l["price"] > prev_l["price"]
    bearish = last_h["price"] < prev_h["price"] and last_l["price"] < prev_l["price"]

    if bullish:
        state = "bullish"
    elif bearish:
        state = "bearish"
    else:
        state = "ranging"

    # Strength heuristic: strong swing if it cleared the prior by >0.5 ATR
    current_price = float(df["close"].iloc[-1])
    atr = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1])

    h_strength = "strong" if abs(last_h["price"] - prev_h["price"]) > 0.5 * atr else "weak"
    l_strength = "strong" if abs(last_l["price"] - prev_l["price"]) > 0.5 * atr else "weak"

    # Bars since last swing
    last_swing_ts = max(last_h["ts"], last_l["ts"])
    bars_in_state = int((df.index[-1] - last_swing_ts).total_seconds() //
                        (df.index[1] - df.index[0]).total_seconds())

    return {
        "state": state,
        "last_swing_high": _fmt_swing(last_h, h_strength),
        "last_swing_low": _fmt_swing(last_l, l_strength),
        "bars_in_state": bars_in_state,
        "current_price": round(current_price, 2),
        "atr_14": round(atr, 2),
    }


def _fmt_swing(s: dict, strength: str) -> dict:
    return {
        "price": round(s["price"], 2),
        "ts": s["ts"].isoformat(),
        "strength": strength,
    }
