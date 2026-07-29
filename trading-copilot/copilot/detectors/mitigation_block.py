"""
Mitigation Block detector.

A Mitigation Block is a (swing-break) Order Block formed by an impulsive
structural break that occurred WITHOUT first sweeping the opposing liquidity
pool (root causes R3 single-OB, R4 pool-anchored sweeps).

Standard ICT flow (sponsored / clean):
  Sellside pool swept → bullish OB → impulse up
  Buyside  pool swept → bearish OB → impulse down

Mitigation Block flow (the anomaly):
  Bullish OB without first sweeping the prior sellside pool → Bullish Mitigation Block
  Bearish OB without first sweeping the prior buyside pool → Bearish Mitigation Block

Consequence: because the opposing liquidity was NOT collected before the move,
institutions must return to the Mitigation Block zone to complete their orders
("mitigate" the remaining fills) — a high-probability draw on price.

Detection:
  1. Find swing-break OBs via the shared scan (the single OB universe).
  2. The pool = the nearest prior swing extreme before the OB candle.
  3. If NO sweep of that pool preceded the OB → Mitigation Block.
  4. Return unmitigated blocks first.
"""

import pandas as pd

from copilot.detectors.order_block import scan_order_blocks
from copilot.detectors.utils import extract_arrays, find_sweep, is_zone_mitigated

TOOL_SCHEMA = {
    "name": "detect_mitigation_block",
    "description": (
        "Find Mitigation Blocks — Order Blocks formed without first sweeping the prior opposing "
        "liquidity pool. These zones are high-probability because institutions must return to "
        "complete their orders ('mitigate'). "
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
                "default": 5,
                "description": "Bars up to the OB candle to check for a prior pool sweep",
            },
            "max_results": {"type": "integer", "default": 5},
            "swing_lookback": {"type": "integer", "default": 5},
        },
        "required": ["symbol", "timeframe"],
    },
}


def detect_mitigation_block(
    df: pd.DataFrame,
    lookback: int = 100,
    sweep_window: int = 5,
    max_results: int = 5,
    swing_lookback: int = 5,
) -> dict:
    if len(df) < 12:
        return {
            "status": "insufficient_data",
            "needed": 12,
            "got": len(df),
            "blocks": [],
            "count": 0,
        }

    from copilot.detectors.market_structure import _find_raw_swings

    _, highs, lows, closes, tss = extract_arrays(df)
    n = len(df)
    raw = _find_raw_swings(df, swing_lookback)
    swing_lows = [s for s in raw if s["type"] == "low"]
    swing_highs = [s for s in raw if s["type"] == "high"]

    blocks: list[dict] = []
    for c in scan_order_blocks(df, swing_lookback=swing_lookback, lookback=lookback):
        ob_h, ob_l, ob_idx, brk = c["ob_high"], c["ob_low"], c["ob_idx"], c["break_idx"]
        ws = max(0, ob_idx - sweep_window)

        if c["type"] == "bullish":
            pool = _nearest_pool(swing_lows, ob_idx)
            swept = pool is not None and find_sweep(
                lows[ws:ob_idx + 1], closes[ws:ob_idx + 1], pool["price"], "sellside"
            )[0]
            if swept:
                continue  # opposing liquidity collected → sponsored, not mitigation
            is_mit = is_zone_mitigated(ob_h, ob_l, lows[brk + 1:], "bullish")
            note = "bullish impulse without a prior sellside pool sweep"
        else:
            pool = _nearest_pool(swing_highs, ob_idx)
            swept = pool is not None and find_sweep(
                highs[ws:ob_idx + 1], closes[ws:ob_idx + 1], pool["price"], "buyside"
            )[0]
            if swept:
                continue
            is_mit = is_zone_mitigated(ob_h, ob_l, highs[brk + 1:], "bearish")
            note = "bearish impulse without a prior buyside pool sweep"

        blocks.append({
            "type": c["type"],
            "high": round(ob_h, 2),
            "low": round(ob_l, 2),
            "formed_ts": tss[ob_idx].isoformat(),
            "is_mitigated": is_mit,
            "age_bars": n - 1 - ob_idx,
            "note": note,
        })

    # Unmitigated first (still need to be revisited), then recency
    blocks.sort(key=lambda x: (x["is_mitigated"], x["age_bars"]))
    result = blocks[:max_results]
    return {"blocks": result, "count": len(result)}


def _nearest_pool(swings: list[dict], ref_idx: int) -> dict | None:
    """The most recent swing strictly before ``ref_idx`` (the nearest prior pool)."""
    prior = [s for s in swings if s["idx"] < ref_idx]
    return prior[-1] if prior else None
