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
  - Divergence (P0-5 rewrite): the window's CONFIRMED price extreme vs the
    CD path. Bearish: price printed its highest high at bar i* (confirmed,
    not the live bar) while CD had already peaked earlier and was lower at
    i* — buyers did not back the new high. Bullish symmetric. The old
    last-bar-vs-fixed-lag scan fired on noise and only at the right edge.
  - Sweep confirmation (P0-5 rewrite): anchored to liquidity POOLS with
    side semantics via detect_liquidity (wick beyond pool level + close
    back). confirmed_manipulation=true when the sweep bar's delta
    contradicts the sweep direction (buyside raid on sell-dominated flow).
    A candle that CLOSES through the level is a break — never reported.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from copilot.detectors.liquidity import detect_liquidity

TOOL_SCHEMA = {
    "name": "detect_cumulative_delta",
    "description": (
        "Compute Cumulative Delta (aggressive buy volume minus sell volume) "
        "per bar using Binance klines taker data. Returns net session delta, "
        "trend direction, divergence at the confirmed price extreme, and "
        "pool-anchored sweep confirmation. Secondary confluence only — "
        "never the primary entry trigger."
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

    result: dict = {
        "period": period,
        "session_delta": session_delta,
        "delta_trend": delta_trend,
        "divergences": _detect_divergences(ohlcv, cd.values),
        "bars": bars_out,
    }
    sweep = _detect_sweep_confirmation(ohlcv, bar_delta.values)
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


def _detect_divergences(ohlcv: pd.DataFrame, cd: np.ndarray) -> list[dict]:
    """Divergence at the window's confirmed price extreme (P0-5, R5 fix).

    Bearish: the bar with the window's highest high (i*, confirmed by at
    least one later closed bar) printed while CD had already peaked at an
    earlier bar and sat lower at i* — price made the high without buyer
    backing. Bullish symmetric (lowest low while CD had bottomed earlier
    and was higher at i*).

    In an aligned trend CD keeps making its extreme AT the price extreme,
    so no divergence fires — verified by test fixtures either way.
    """
    n = len(ohlcv)
    if n < 6:
        return []

    highs = ohlcv["high"].values
    lows = ohlcv["low"].values
    tss = ohlcv.index
    divergences: list[dict] = []

    # Bearish: price extreme high, CD peaked earlier and is lower at i*
    i_star = int(np.argmax(highs))
    if i_star <= n - 2:  # confirmed: not the live right-edge bar
        j = int(np.argmax(cd[: i_star + 1]))
        if j < i_star and cd[i_star] < cd[j]:
            divergences.append({
                "type": "bearish",
                "price_high": round(float(highs[i_star]), 2),
                "cd_at_high": round(float(cd[i_star]), 4),
                "bar_ts": tss[i_star].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "context": "price_new_high_cd_falling",
            })

    # Bullish: price extreme low, CD bottomed earlier and is higher at i*
    i_star = int(np.argmin(lows))
    if i_star <= n - 2:
        j = int(np.argmin(cd[: i_star + 1]))
        if j < i_star and cd[i_star] > cd[j]:
            divergences.append({
                "type": "bullish",
                "price_low": round(float(lows[i_star]), 2),
                "cd_at_low": round(float(cd[i_star]), 4),
                "bar_ts": tss[i_star].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "context": "price_new_low_cd_rising",
            })

    return divergences


def _detect_sweep_confirmation(ohlcv: pd.DataFrame, bar_delta: np.ndarray) -> dict | None:
    """Most recent pool-anchored liquidity sweep + the delta verdict (R4/R5 fix).

    Sweeps come from detect_liquidity: wick beyond a side-typed liquidity
    pool with the candle closing back inside. confirmed_manipulation=true
    when the sweep bar's delta contradicts the raid direction — a buyside
    sweep printed on net selling (or sellside on net buying) is stop-hunt
    fuel, not genuine demand.
    """
    liq = detect_liquidity(ohlcv[["open", "high", "low", "close", "volume"]])
    sweeps = liq.get("recent_sweeps") or []
    if not sweeps:
        return None

    latest = sweeps[0]  # newest-first
    ts_strs = [str(ts) for ts in ohlcv.index]
    try:
        bar_i = ts_strs.index(latest["sweep_ts"])
    except ValueError:
        return None

    delta_val = float(bar_delta[bar_i])
    if latest["side"] == "buyside":
        confirmed = delta_val < 0  # swept the highs while sellers dominated
    else:
        confirmed = delta_val > 0  # swept the lows while buyers dominated

    return {
        "last_sweep_ts": ohlcv.index[bar_i].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sweep_side": latest["side"],
        "cd_at_sweep": round(delta_val, 4),
        "confirmed_manipulation": confirmed,
    }
