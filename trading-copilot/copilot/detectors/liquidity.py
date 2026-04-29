"""
Liquidity pool detector: Equal Highs/Lows (EQH/EQL), swing pools, sweeps.

Liquidity sits above swing highs (buyside) and below swing lows (sellside).
A "sweep" = wick pierces the level but candle closes back on the opposite side.

Per KB: a confirmed sweep (wick only, closed back) is the primary trigger for
the 1h3m and Silver Bullet setups.
"""

import pandas as pd
import numpy as np

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
        },
        "required": ["symbol", "timeframe"],
    },
}


def detect_liquidity(
    df: pd.DataFrame,
    tolerance_atr: float = 0.15,
    lookback: int = 150,
    max_results: int = 6,
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

    atr = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1])
    tol = atr * tolerance_atr

    window = df.iloc[-lookback:]
    highs = window["high"].values
    lows = window["low"].values
    closes = window["close"].values
    tss = window.index

    buyside: list[dict] = []
    sellside: list[dict] = []

    # Swing highs/lows via local maxima (3-bar fractals)
    for i in range(1, len(window) - 1):
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            swept = bool((highs[i + 1 :] > highs[i]).any())
            touches = _count_touches(highs, highs[i], tol, i)
            buyside.append({
                "price": round(float(highs[i]), 2),
                "type": "EQH" if touches >= 2 else "swing_high",
                "touches": touches,
                "last_touch_ts": tss[i].isoformat(),
                "age_bars": len(window) - 1 - i,
                "is_swept": swept,
            })
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            swept = bool((lows[i + 1 :] < lows[i]).any())
            touches = _count_touches(lows, lows[i], tol, i, is_high=False)
            sellside.append({
                "price": round(float(lows[i]), 2),
                "type": "EQL" if touches >= 2 else "swing_low",
                "touches": touches,
                "last_touch_ts": tss[i].isoformat(),
                "age_bars": len(window) - 1 - i,
                "is_swept": swept,
            })

    # Detect recent sweeps in last 30 bars
    sweeps = _find_sweeps(window, buyside + sellside, atr)

    # Filter to unswept only, sort by recency
    active_buy = [p for p in buyside if not p["is_swept"]]
    active_sell = [p for p in sellside if not p["is_swept"]]
    active_buy.sort(key=lambda x: x["age_bars"])
    active_sell.sort(key=lambda x: x["age_bars"])

    # Clean output: remove internal "is_swept" flag
    for p in active_buy + active_sell:
        p.pop("is_swept", None)

    return {
        "buyside_liquidity": active_buy[:max_results],
        "sellside_liquidity": active_sell[:max_results],
        "recent_sweeps": sweeps[:max_results],
    }


def _count_touches(prices: np.ndarray, level: float, tol: float, idx: int, is_high: bool = True) -> int:
    """Count bars where price came within tolerance of the level."""
    return int((np.abs(prices - level) <= tol).sum())


def _find_sweeps(window: pd.DataFrame, pools: list[dict], atr: float) -> list[dict]:
    """Detect wick-only raids (wick past level, close returns)."""
    sweeps: list[dict] = []
    scan = window.iloc[-30:]
    highs = scan["high"].values
    lows = scan["low"].values
    closes = scan["close"].values
    tss = scan.index

    for pool in pools:
        level = pool["price"]
        is_buy = pool in [p for p in pools if "swing_high" in p["type"] or "EQH" in p["type"]]
        tol = atr * 0.05

        for i in range(len(scan) - 1):
            # Buyside sweep: wick above level but close below
            if highs[i] > level + tol and closes[i] < level:
                sweeps.append({
                    "side": "buyside",
                    "swept_level": level,
                    "sweep_ts": tss[i].isoformat(),
                    "closed_back": True,
                })
            # Sellside sweep: wick below level but close above
            elif lows[i] < level - tol and closes[i] > level:
                sweeps.append({
                    "side": "sellside",
                    "swept_level": level,
                    "sweep_ts": tss[i].isoformat(),
                    "closed_back": True,
                })

    # Deduplicate by ts
    seen = set()
    unique = []
    for s in sweeps:
        key = (s["side"], s["swept_level"], s["sweep_ts"])
        if key not in seen:
            seen.add(key)
            unique.append(s)

    unique.sort(key=lambda x: x["sweep_ts"], reverse=True)
    return unique
