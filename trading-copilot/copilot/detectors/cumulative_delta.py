"""
Cumulative Delta (CD) detector.

Requires a DataFrame with OHLCV + buy_vol / sell_vol / delta columns,
produced by fetch_ohlcv_with_delta(). Binance klines include
taker_buy_base_vol, so no tick-level data or aggTrades pagination is needed.

  buy_vol  = taker_buy_base_vol   (aggressive buyers, Ask side)
  sell_vol = volume - buy_vol     (aggressive sellers, Bid side)
  delta    = buy_vol - sell_vol

Signals:
  - Session net delta + trend direction (positive / negative / neutral)
  - Bearish divergence: price new high, CD not confirming
  - Bullish divergence: price new low, CD not confirming
  - Sweep confirmation: wick through a recent extreme, delta contradicts the
    direction → manipulation signal (KB-aligned interpretation)
"""

from __future__ import annotations

import pandas as pd

TOOL_SCHEMA = {
    "name": "detect_cumulative_delta",
    "description": (
        "Compute Cumulative Delta (aggressive buy volume minus sell volume) "
        "per bar using Binance klines taker data. Returns net session delta, "
        "trend direction, divergence signals, and sweep confirmation. "
        "Use to confirm or dispute a liquidity sweep — if CD did not rise "
        "with a BSL sweep, manipulation is confirmed. Also use at POI to detect "
        "hidden absorption before a reversal."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "e.g. BTCUSDT"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "bars": {
                "type": "integer",
                "default": 100,
                "description": "Number of bars to analyse",
            },
            "period": {
                "type": "string",
                "enum": ["session", "week", "all"],
                "default": "session",
                "description": (
                    "Time window for CD accumulation. "
                    "'session' = last 24 h, 'week' = last 7 d, 'all' = full df."
                ),
            },
        },
        "required": ["symbol", "timeframe"],
    },
}

_PERIOD_TD = {
    "session": pd.Timedelta("24h"),
    "week": pd.Timedelta("7D"),
}


def detect_cumulative_delta(df: pd.DataFrame, period: str = "session") -> dict:
    """
    df: OHLCV + buy_vol + sell_vol + delta columns (from fetch_ohlcv_with_delta).
    Returns compact JSON with CD signals the LLM can reason over.
    """
    if "buy_vol" not in df.columns or "delta" not in df.columns:
        return {
            "status": "insufficient_data",
            "reason": "DataFrame missing buy_vol/delta columns — use fetch_ohlcv_with_delta",
        }

    if len(df) < 5:
        return {"status": "insufficient_data", "needed": 5, "got": len(df)}

    ohlcv = _trim_period(df, period)
    if len(ohlcv) < 3:
        ohlcv = df  # fallback: too few bars after trim

    # Per-bar delta series
    bar_delta = ohlcv["delta"]
    cd = bar_delta.cumsum()

    # Session net delta
    session_delta = round(float(cd.iloc[-1]), 4)

    # Trend: compare last bar's CD to 5 bars ago
    lookback = min(5, len(cd) - 1)
    slope = float(cd.iloc[-1]) - float(cd.iloc[-1 - lookback])
    if slope > 0:
        delta_trend = "positive"
    elif slope < 0:
        delta_trend = "negative"
    else:
        delta_trend = "neutral"

    divergences = _detect_divergences(ohlcv, cd)
    sweep = _detect_sweep_signal(ohlcv, bar_delta)

    bars_out = [
        {
            "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "delta": round(float(d), 4),
            "cumulative": round(float(c), 4),
        }
        for ts, d, c in zip(ohlcv.index, bar_delta, cd)
    ][-50:]  # cap output at 50 bars

    result: dict = {
        "period": period,
        "session_delta": session_delta,
        "delta_trend": delta_trend,
        "divergences": divergences,
        "bars": bars_out,
    }
    if sweep:
        result["sweep_confirmation"] = sweep
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _trim_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    td = _PERIOD_TD.get(period)
    if td is None:
        return df
    cutoff = df.index[-1] - td
    trimmed = df[df.index >= cutoff]
    return trimmed if len(trimmed) >= 3 else df


def _detect_divergences(ohlcv: pd.DataFrame, cd: pd.Series, window: int = 10) -> list[dict]:
    """Compare recent bars to bars N steps earlier for price/CD divergence."""
    if len(ohlcv) < 4:
        return []

    divergences: list[dict] = []
    n = min(window, len(ohlcv) - 2)

    for lag in range(2, n + 1):
        curr_high = float(ohlcv["high"].iloc[-1])
        prev_high = float(ohlcv["high"].iloc[-lag])
        curr_low = float(ohlcv["low"].iloc[-1])
        prev_low = float(ohlcv["low"].iloc[-lag])
        curr_cd = float(cd.iloc[-1])
        prev_cd = float(cd.iloc[-lag])

        # Bearish: price higher but CD lower
        if curr_high > prev_high and curr_cd < prev_cd and not divergences:
            divergences.append({
                "type": "bearish",
                "price_high": round(curr_high, 2),
                "cd_at_high": round(curr_cd, 4),
                "bar_ts": ohlcv.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "context": "price_new_high_cd_falling",
            })
            break

        # Bullish: price lower but CD higher
        if curr_low < prev_low and curr_cd > prev_cd and not divergences:
            divergences.append({
                "type": "bullish",
                "price_low": round(curr_low, 2),
                "cd_at_low": round(curr_cd, 4),
                "bar_ts": ohlcv.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "context": "price_new_low_cd_rising",
            })
            break

    return divergences


def _detect_sweep_signal(
    ohlcv: pd.DataFrame,
    bar_delta: pd.Series,
    lookback: int = 8,
    wick_threshold: float = 0.002,
) -> dict | None:
    """Find the most recent bar that looks like a wick sweep and check if CD contradicts it."""
    n = min(lookback, len(ohlcv) - 2)
    if n < 1:
        return None

    for i in range(1, n + 1):
        bar = ohlcv.iloc[-i]
        ref = ohlcv.iloc[-(i + 4) : -i] if i + 4 <= len(ohlcv) else ohlcv.iloc[:-i]
        if len(ref) == 0:
            continue

        delta_val = float(bar_delta.iloc[-i])
        ts_str = ohlcv.index[-i].strftime("%Y-%m-%dT%H:%M:%SZ")
        bar_range = float(bar["high"] - bar["low"])

        # Buyside sweep: wick above ref highs, close returns below
        upper_wick = float(bar["high"] - max(bar["open"], bar["close"]))
        if (
            float(bar["high"]) > float(ref["high"].max())
            and bar_range > 0
            and upper_wick / bar_range > wick_threshold
        ):
            return {
                "last_sweep_ts": ts_str,
                "sweep_side": "buyside",
                "cd_at_sweep": round(delta_val, 4),
                "confirmed_manipulation": delta_val < 0,  # swept high but sellers dominated
            }

        # Sellside sweep: wick below ref lows, close returns above
        lower_wick = float(min(bar["open"], bar["close"]) - bar["low"])
        if (
            float(bar["low"]) < float(ref["low"].min())
            and bar_range > 0
            and lower_wick / bar_range > wick_threshold
        ):
            return {
                "last_sweep_ts": ts_str,
                "sweep_side": "sellside",
                "cd_at_sweep": round(delta_val, 4),
                "confirmed_manipulation": delta_val > 0,  # swept low but buyers dominated
            }

    return None
