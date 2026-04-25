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
        },
        "required": ["symbol", "timeframe", "swing_high", "swing_low"],
    },
}


def detect_fib_zones(
    df: pd.DataFrame,
    swing_high: float,
    swing_low: float,
) -> dict:
    if swing_high <= swing_low:
        return {"status": "invalid_swing", "reason": "swing_high must be > swing_low"}

    rng = swing_high - swing_low
    current_price = round(float(df["close"].iloc[-1]), 2)

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

    fib_ratio = (swing_high - current_price) / rng if rng else 0

    return {
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
        "equilibrium": equilibrium,
        "premium_zone": {"upper": round(swing_high, 2), "lower": equilibrium},
        "discount_zone": {"upper": equilibrium, "lower": round(swing_low, 2)},
        "ote": {
            "upper": levels["0.618"],
            "lower": levels["0.786"],
            "midpoint": levels["0.705"],
        },
        "current_price": current_price,
        "current_fib_ratio": round(fib_ratio, 3),
        "current_price_location": price_location,
        "in_ote": levels["0.786"] <= current_price <= levels["0.618"],
        "key_levels": levels,
    }
