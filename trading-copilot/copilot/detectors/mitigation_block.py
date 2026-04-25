"""
Mitigation Block detector.

A Mitigation Block is an Order Block formed by an impulsive structural break
that occurred WITHOUT sweeping the opposing liquidity pool first.

Standard ICT flow:
  Sellside liquidity swept → bullish OB → impulse up   (sponsored/clean)
  Buyside  liquidity swept → bearish OB → impulse down (sponsored/clean)

Mitigation Block flow (the anomaly):
  Bullish impulse WITHOUT first sweeping the sellside low  → Bullish Mitigation Block
  Bearish impulse WITHOUT first sweeping the buyside high  → Bearish Mitigation Block

Consequence: because the opposing liquidity was NOT collected before the move,
institutions MUST return to the Mitigation Block zone to complete their orders
("mitigate" the remaining fills). This makes the zone a high-probability draw.

Detection logic:
  1. Same OB pattern as detect_order_block (opposing candle + impulse close).
  2. In the `sweep_window` bars BEFORE the OB candle, check whether the opposing
     liquidity pool (local swing extreme) was swept (wick + close-back confirmation).
  3. If NO sweep preceded the OB → Mitigation Block.
  4. Return unmitigated blocks (zone midpoint not yet visited).
"""

import numpy as np
import pandas as pd

TOOL_SCHEMA = {
    "name": "detect_mitigation_block",
    "description": (
        "Find Mitigation Blocks — Order Blocks formed without a prior liquidity sweep. "
        "These zones are high-probability because institutions must return to complete "
        "their orders ('mitigate'). "
        "Use when the market made an impulsive move but opposing stops were not taken first."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "lookback": {"type": "integer", "default": 100},
            "sweep_window": {
                "type": "integer",
                "default": 8,
                "description": "Bars before the OB to check for a prior sweep",
            },
            "max_results": {"type": "integer", "default": 5},
        },
        "required": ["symbol", "timeframe"],
    },
}

_IMPULSE_ATR_THRESHOLD = 1.5


def detect_mitigation_block(
    df: pd.DataFrame,
    lookback: int = 100,
    sweep_window: int = 8,
    max_results: int = 5,
) -> dict:
    if len(df) < 12:
        return {
            "status": "insufficient_data",
            "needed": 12,
            "got": len(df),
            "blocks": [],
            "count": 0,
        }

    atr = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1])
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    tss = df.index

    blocks: list[dict] = []
    start_i = max(sweep_window + 1, len(df) - lookback - 1)

    for i in range(start_i, len(df) - 2):
        impulse_range = highs[i + 1] - lows[i + 1]

        # ── Bullish OB: bearish candle → bullish impulse ──
        if closes[i] < opens[i] and closes[i + 1] > highs[i] and impulse_range > _IMPULSE_ATR_THRESHOLD * atr:
            ob_high = max(opens[i], closes[i])
            ob_low = min(opens[i], closes[i])

            # Look for a sellside sweep in the window before the OB:
            # A wick below ob_low that closes back above ob_low → sellside swept
            pre_start = max(0, i - sweep_window)
            pre_lows = lows[pre_start:i]
            pre_closes = closes[pre_start:i]

            prior_sweep = _has_sweep_of_level(pre_lows, pre_closes, ob_low, side="sellside")

            if prior_sweep:
                continue  # Liquidity was swept → regular sponsored OB, skip

            # Only include if zone is not yet mitigated (midpoint not visited)
            future_lows = lows[i + 2:]
            midpoint = (ob_high + ob_low) / 2
            is_mitigated = len(future_lows) > 0 and bool((future_lows <= midpoint).any())

            blocks.append({
                "type": "bullish",
                "high": round(ob_high, 2),
                "low": round(ob_low, 2),
                "formed_ts": tss[i].isoformat(),
                "is_mitigated": is_mitigated,
                "age_bars": len(df) - 1 - i,
                "note": "move initiated without prior sellside sweep",
            })

        # ── Bearish OB: bullish candle → bearish impulse ──
        if closes[i] > opens[i] and closes[i + 1] < lows[i] and impulse_range > _IMPULSE_ATR_THRESHOLD * atr:
            ob_high = max(opens[i], closes[i])
            ob_low = min(opens[i], closes[i])

            # Look for a buyside sweep in the window before the OB:
            # A wick above ob_high that closes back below ob_high → buyside swept
            pre_start = max(0, i - sweep_window)
            pre_highs = highs[pre_start:i]
            pre_closes = closes[pre_start:i]

            prior_sweep = _has_sweep_of_level(pre_highs, pre_closes, ob_high, side="buyside")

            if prior_sweep:
                continue  # Liquidity swept → regular sponsored OB, skip

            future_highs = highs[i + 2:]
            midpoint = (ob_high + ob_low) / 2
            is_mitigated = len(future_highs) > 0 and bool((future_highs >= midpoint).any())

            blocks.append({
                "type": "bearish",
                "high": round(ob_high, 2),
                "low": round(ob_low, 2),
                "formed_ts": tss[i].isoformat(),
                "is_mitigated": is_mitigated,
                "age_bars": len(df) - 1 - i,
                "note": "move initiated without prior buyside sweep",
            })

    # Unmitigated first (still need to be revisited), then recency
    blocks.sort(key=lambda x: (x["is_mitigated"], x["age_bars"]))
    result = blocks[:max_results]
    return {"blocks": result, "count": len(result)}


def _has_sweep_of_level(
    wicks: np.ndarray,
    closes: np.ndarray,
    level: float,
    side: str,
) -> bool:
    """
    Check if any bar has a wick past `level` that closes back on the safe side.

    sellside: wick below level (low < level) AND close > level
    buyside:  wick above level (high > level) AND close < level
    """
    for j in range(len(wicks)):
        if side == "sellside":
            if wicks[j] < level and closes[j] > level:
                return True
        else:  # buyside
            if wicks[j] > level and closes[j] < level:
                return True
    return False
