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

Divergence and sweep-confirmation signals were removed in June 2026
(Course Correction #2, PLAN.md P0-4): the last-bar-vs-fixed-lag divergence
and the 0.2%-wick "sweep" check were shown by probes to fire on noise.
They will return as swing-to-swing / pool-anchored implementations (P0-5).
"""

from __future__ import annotations

import pandas as pd

TOOL_SCHEMA = {
    "name": "detect_cumulative_delta",
    "description": (
        "Compute Cumulative Delta (aggressive buy volume minus sell volume) "
        "per bar using Binance klines taker data. Returns net session delta "
        "and trend direction. Use as directional context only — it does not "
        "confirm sweeps or divergences."
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

    bars_out = [
        {
            "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "delta": round(float(d), 4),
            "cumulative": round(float(c), 4),
        }
        for ts, d, c in zip(ohlcv.index, bar_delta, cd)
    ][-50:]  # cap output at 50 bars

    return {
        "period": period,
        "session_delta": session_delta,
        "delta_trend": delta_trend,
        "bars": bars_out,
    }


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


# _detect_divergences and _detect_sweep_signal were deleted here (P0-4):
# both compared only the last bar against fixed lags/thresholds and fired on
# noise. Rewrite swing-to-swing / pool-anchored under P0-5.
