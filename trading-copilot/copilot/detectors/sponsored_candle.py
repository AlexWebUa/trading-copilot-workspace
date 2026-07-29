"""
Sponsored Candle detector.

A Sponsored Candle is a (swing-break) Order Block that was IMMEDIATELY PRECEDED
by a confirmed sweep of a *liquidity pool* — a prior swing extreme — not of the
OB's own boundary (root causes R3 single-OB, R4 pool-anchored sweeps).

  Sellside pool (prior swing LOW) swept  → bullish OB → bullish impulse
  Buyside  pool (prior swing HIGH) swept → bearish OB → bearish impulse

Why it matters (per KB):
  The sweep "sponsored" the institutional order — resting stops at the pool were
  taken, fuel was collected, then price reversed into the OB and impulsed away.
  This is the highest-probability OB variant.

Detection:
  1. Find swing-break OBs via the shared scan (the single OB universe).
  2. The pool = the nearest prior swing extreme before the OB candle (sellside
     low for a bullish OB, buyside high for a bearish OB).
  3. Sweep = within `sweep_window` bars up to the OB candle, a wick beyond the
     pool that closes back on the safe side (find_sweep, side-typed).
  4. Return sponsored OBs (unmitigated first).
"""

import pandas as pd

from copilot.detectors.order_block import scan_order_blocks
from copilot.detectors.utils import extract_arrays, find_sweep, is_zone_mitigated

TOOL_SCHEMA = {
    "name": "detect_sponsored_candle",
    "description": (
        "Find Sponsored Candles — Order Blocks immediately preceded by a confirmed sweep of a "
        "liquidity pool (a prior swing high/low). These are the highest-quality OBs: institutions "
        "swept stops at the pool then entered the impulse. "
        "Use to identify setups where both a pool sweep AND an OB are present for maximum confluence."
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
                "description": "Bars up to the OB candle to scan for the sponsoring pool sweep",
            },
            "max_results": {"type": "integer", "default": 4},
            "swing_lookback": {"type": "integer", "default": 5},
        },
        "required": ["symbol", "timeframe"],
    },
}


def detect_sponsored_candle(
    df: pd.DataFrame,
    lookback: int = 100,
    sweep_window: int = 5,
    max_results: int = 4,
    swing_lookback: int = 5,
) -> dict:
    if len(df) < 10:
        return {
            "status": "insufficient_data",
            "needed": 10,
            "got": len(df),
            "candles": [],
            "count": 0,
        }

    from copilot.detectors.market_structure import _find_raw_swings

    _, highs, lows, closes, tss = extract_arrays(df)
    n = len(df)
    raw = _find_raw_swings(df, swing_lookback)
    swing_lows = [s for s in raw if s["type"] == "low"]
    swing_highs = [s for s in raw if s["type"] == "high"]

    sponsored: list[dict] = []
    for c in scan_order_blocks(df, swing_lookback=swing_lookback, lookback=lookback):
        ob_h, ob_l, ob_idx, brk = c["ob_high"], c["ob_low"], c["ob_idx"], c["break_idx"]
        ws = max(0, ob_idx - sweep_window)

        if c["type"] == "bullish":
            pool = _nearest_pool(swing_lows, ob_idx)
            if pool is None:
                continue
            found, rel = find_sweep(lows[ws:ob_idx + 1], closes[ws:ob_idx + 1], pool["price"], "sellside")
            if not found:
                continue
            is_mit = is_zone_mitigated(ob_h, ob_l, lows[brk + 1:], "bullish")
            sweep_side = "sellside"
        else:
            pool = _nearest_pool(swing_highs, ob_idx)
            if pool is None:
                continue
            found, rel = find_sweep(highs[ws:ob_idx + 1], closes[ws:ob_idx + 1], pool["price"], "buyside")
            if not found:
                continue
            is_mit = is_zone_mitigated(ob_h, ob_l, highs[brk + 1:], "bearish")
            sweep_side = "buyside"

        sponsored.append({
            "ob_type": c["type"],
            "high": round(ob_h, 2),
            "low": round(ob_l, 2),
            "formed_ts": tss[ob_idx].isoformat(),
            "sweep_ts": tss[ws + rel].isoformat(),
            "sweep_side": sweep_side,
            "pool_price": round(pool["price"], 2),
            "is_mitigated": is_mit,
            "age_bars": n - 1 - ob_idx,
        })

    # Unmitigated first, then recency
    sponsored.sort(key=lambda x: (x["is_mitigated"], x["age_bars"]))
    result = sponsored[:max_results]
    return {"candles": result, "count": len(result)}


def _nearest_pool(swings: list[dict], ref_idx: int) -> dict | None:
    """The most recent swing strictly before ``ref_idx`` (the nearest prior pool)."""
    prior = [s for s in swings if s["idx"] < ref_idx]
    return prior[-1] if prior else None
