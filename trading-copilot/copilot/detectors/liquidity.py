"""
Liquidity pool detector: Equal Highs/Lows (EQH/EQL), swing pools, sweeps.

Rewritten June 2026 (P0-3) on `smartmoneyconcepts`:
  - EQH/EQL pools come from smc.liquidity (grouped equal swing levels).
  - Single confirmed swings are added as swing_high / swing_low pools.
  - Sweep detection is POOL-ANCHORED with SIDE SEMANTICS (root cause R4):
    a buyside sweep can only happen AT a buyside pool (a high) — wick
    pierces above the level, candle CLOSES back below. A candle that
    CLOSES through the level is a break, not a sweep, and is never
    reported in recent_sweeps. The old code tested every level with both
    geometries, so a wide bullish bar crossing a swing high printed as a
    "sellside sweep, closed_back=true" of that high.

Pools that price has already traded beyond (swept or broken) are excluded
from the active buyside/sellside lists.
"""

import numpy as np
import pandas as pd

from copilot.detectors.smc_lib import confirmed_swings, lib_swings, smc, true_range_atr

TOOL_SCHEMA = {
    "name": "detect_liquidity",
    "description": (
        "Find buyside and sellside liquidity pools (Equal Highs/Lows, swing pools) "
        "and recent liquidity sweeps (wick raids with close-back confirmation). "
        "Use to identify where stop-losses cluster and check if a sweep has occurred "
        "before expecting a directional move."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "tolerance_atr": {
                "type": "number",
                "default": 0.15,
                "description": "EQH/EQL matching tolerance as fraction of ATR",
            },
            "lookback": {"type": "integer", "default": 150},
            "max_results": {"type": "integer", "default": 6},
            "swing_lookback": {
                "type": "integer",
                "default": 3,
                "description": "Bars each side to confirm a swing pivot",
            },
        },
        "required": ["symbol", "timeframe"],
    },
}

# Sweep scan covers this many most-recent bars
_SWEEP_SCAN_BARS = 30


def detect_liquidity(
    df: pd.DataFrame,
    tolerance_atr: float = 0.15,
    lookback: int = 80,
    max_results: int = 6,
    swing_lookback: int = 3,
) -> dict:
    if len(df) < 10:
        return {
            "status": "insufficient_data",
            "needed": 10,
            "got": len(df),
            "buyside_liquidity": [],
            "sellside_liquidity": [],
            "recent_sweeps": [],
        }

    ohlc = df.iloc[-lookback:]
    tss = [str(ts) for ts in ohlc.index]
    n = len(ohlc)

    atr = float(true_range_atr(ohlc)[-1])
    tol = atr * tolerance_atr if atr > 0 else 0.0

    # Halted / all-same-price market: no range → no swing structure.
    # The library's tie-tolerant swing detection would otherwise mark a
    # "swing" on a perfectly flat chart (documented edge case in PLAN.md).
    chart_range = float(ohlc["high"].max() - ohlc["low"].min())
    if chart_range <= 0:
        return {
            "buyside_liquidity": [],
            "sellside_liquidity": [],
            "recent_sweeps": [],
        }

    shl = lib_swings(ohlc, swing_lookback)
    swings = confirmed_swings(shl, ohlc)

    # ── EQH/EQL pools from the library ──────────────────────────────────
    range_percent = (tol / chart_range) if chart_range > 0 else 0.01
    pools_df = smc.liquidity(ohlc, shl, range_percent=range_percent)

    pooled_levels: list[dict] = []   # internal: {side, level, touches, end_idx}
    grouped_swing_idx: set[int] = set()

    liq = pools_df["Liquidity"].values
    lvl = pools_df["Level"].values
    end = pools_df["End"].values
    for i in range(n):
        if np.isnan(liq[i]):
            continue
        side = "buyside" if liq[i] == 1 else "sellside"
        level = float(lvl[i])
        end_idx = int(end[i]) if not np.isnan(end[i]) else i
        members = [
            s for s in swings
            if (s["type"] == ("high" if side == "buyside" else "low"))
            and abs(s["price"] - level) <= max(tol, 1e-9)
        ]
        grouped_swing_idx.update(s["idx"] for s in members)
        pooled_levels.append({
            "side": side,
            "level": level,
            "touches": max(len(members), 2),
            "end_idx": end_idx,
        })

    # ── Single confirmed swings not part of an EQ pool ──────────────────
    single_levels: list[dict] = []
    for s in swings:
        if s["idx"] in grouped_swing_idx:
            continue
        single_levels.append({
            "side": "buyside" if s["type"] == "high" else "sellside",
            "level": s["price"],
            "touches": 1,
            "end_idx": s["idx"],
        })

    all_levels = pooled_levels + single_levels

    highs = ohlc["high"].values
    lows = ohlc["low"].values
    closes = ohlc["close"].values

    # ── Sweep scan: pool-anchored, side-typed, close-back required ──────
    sweeps: list[dict] = []
    scan_start = max(0, n - _SWEEP_SCAN_BARS)
    for pool in all_levels:
        level = pool["level"]
        start = max(pool["end_idx"] + 1, scan_start)
        for i in range(start, n):
            if pool["side"] == "buyside":
                # Wick above the high pool, close back below it
                if highs[i] > level + tol and closes[i] < level:
                    sweeps.append({
                        "side": "buyside",
                        "swept_level": round(level, 2),
                        "sweep_ts": tss[i],
                        "closed_back": True,
                    })
                    break  # one sweep event per pool — the first taking
                if closes[i] > level + tol:
                    break  # closed through = break, pool is gone, no sweep
            else:
                if lows[i] < level - tol and closes[i] > level:
                    sweeps.append({
                        "side": "sellside",
                        "swept_level": round(level, 2),
                        "sweep_ts": tss[i],
                        "closed_back": True,
                    })
                    break
                if closes[i] < level - tol:
                    break

    sweeps.sort(key=lambda x: x["sweep_ts"], reverse=True)

    # ── Active pools: price has not yet traded beyond the level ─────────
    buyside: list[dict] = []
    sellside: list[dict] = []
    for pool in all_levels:
        level = pool["level"]
        after = pool["end_idx"] + 1
        if pool["side"] == "buyside":
            taken = bool((highs[after:] > level + tol).any())
        else:
            taken = bool((lows[after:] < level - tol).any())
        if taken:
            continue
        entry = {
            "price": round(level, 2),
            "type": (
                ("EQH" if pool["side"] == "buyside" else "EQL")
                if pool["touches"] >= 2
                else ("swing_high" if pool["side"] == "buyside" else "swing_low")
            ),
            "touches": pool["touches"],
            "last_touch_ts": tss[pool["end_idx"]],
            "age_bars": n - 1 - pool["end_idx"],
        }
        (buyside if pool["side"] == "buyside" else sellside).append(entry)

    buyside.sort(key=lambda x: x["age_bars"])
    sellside.sort(key=lambda x: x["age_bars"])

    return {
        "buyside_liquidity": buyside[:max_results],
        "sellside_liquidity": sellside[:max_results],
        "recent_sweeps": sweeps[:max_results],
    }
