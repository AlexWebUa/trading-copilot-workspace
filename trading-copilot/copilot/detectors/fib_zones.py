"""
Fibonacci Premium/Discount zones and OTE (Optimal Trade Entry) detector.

Given a swing high and swing low, divides the range into:
  premium zone  : price above 0.5 fib (above equilibrium) — optimal for shorts
  discount zone : price below 0.5 fib (below equilibrium) — optimal for longs
  OTE band      : 0.62–0.79 fib (Optimal Trade Entry zone, per ICT/KB)

The LLM provides swing_high and swing_low from its context (via detect_market_structure
or user input). This detector just computes the math and locates current price.
"""

import pandas as pd

TOOL_SCHEMA = {
    "name": "detect_fib_zones",
    "description": (
        "Calculate Fibonacci Premium/Discount zones and OTE band for a given price swing. "
        "Returns zone boundaries and whether current price is in premium, discount, or equilibrium. "
        "Use after identifying a swing to determine if current price is at a high-probability "
        "entry location (discount for longs, premium for shorts)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "swing_high": {
                "type": "number",
                "description": "The high of the reference swing",
            },
            "swing_low": {
                "type": "number",
                "description": "The low of the reference swing",
            },
            "direction": {
                "type": "string",
                "enum": ["auto", "long", "short"],
                "default": "auto",
                "description": (
                    "Trade direction the swing is measured for. 'long' = OTE is the "
                    "0.618–0.786 retracement DOWN from the swing high (discount entry); "
                    "'short' = the 0.618–0.786 retracement UP from the swing low (premium "
                    "entry). 'auto' infers it from the leg in the data."
                ),
            },
        },
        "required": ["symbol", "timeframe", "swing_high", "swing_low"],
    },
}


def detect_fib_zones(
    df: pd.DataFrame,
    swing_high: float,
    swing_low: float,
    direction: str = "auto",
) -> dict:
    if swing_high <= swing_low:
        return {"status": "invalid_swing", "reason": "swing_high must be > swing_low"}

    rng = swing_high - swing_low
    current_price = round(float(df["close"].iloc[-1]), 2)

    if direction == "auto":
        direction = _infer_direction(df)

    # Standard fib ladder measured DOWN from the swing high (retracement %).
    def fib(ratio: float) -> float:
        return round(swing_high - ratio * rng, 2)

    levels = {
        "0.0": round(swing_high, 2),
        "0.236": fib(0.236),
        "0.382": fib(0.382),
        "0.500": fib(0.500),  # equilibrium
        "0.618": fib(0.618),  # OTE start
        "0.705": fib(0.705),  # OTE midpoint
        "0.786": fib(0.786),  # OTE end
        "1.0": round(swing_low, 2),
    }

    equilibrium = levels["0.500"]

    if current_price > equilibrium:
        price_location = "premium"
    elif current_price < equilibrium:
        price_location = "discount"
    else:
        price_location = "equilibrium"

    # OTE band is direction-dependent. For a long (up-leg) we want the discount
    # retracement down from the high; for a short (down-leg) the premium
    # retracement up from the low. Bounds reported low→high regardless.
    if direction == "short":
        ote = {
            "lower": round(swing_low + 0.618 * rng, 2),
            "upper": round(swing_low + 0.786 * rng, 2),
            "midpoint": round(swing_low + 0.705 * rng, 2),
        }
    else:  # long
        ote = {
            "lower": levels["0.786"],
            "upper": levels["0.618"],
            "midpoint": levels["0.705"],
        }

    fib_ratio = (swing_high - current_price) / rng if rng else 0

    return {
        "direction": direction,
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
        "equilibrium": equilibrium,
        "premium_zone": {"upper": round(swing_high, 2), "lower": equilibrium},
        "discount_zone": {"upper": equilibrium, "lower": round(swing_low, 2)},
        "ote": ote,
        "current_price": current_price,
        "current_fib_ratio": round(fib_ratio, 3),
        "current_price_location": price_location,
        "in_ote": ote["lower"] <= current_price <= ote["upper"],
        "key_levels": levels,
    }


def _infer_direction(df: pd.DataFrame) -> str:
    """Infer the leg direction from the data: if the high prints before the low
    the market was falling (short setup, retrace up); otherwise it was rising
    (long setup, retrace down). Ties default to long."""
    highs = df["high"].values
    lows = df["low"].values
    if len(highs) == 0:
        return "long"
    return "short" if int(highs.argmax()) < int(lows.argmin()) else "long"
