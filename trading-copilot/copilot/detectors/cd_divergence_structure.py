"""
CD Divergence at Structure detector.

Synthesises detect_market_structure() + cumulative-delta divergence logic +
detect_liquidity() to flag when CD diverges specifically at a key swing high
or swing low.

The divergence loop is inlined (copied from cumulative_delta._detect_divergences)
to avoid a circular-import chain: cumulative_delta → cd_divergence_structure → …
"""
from __future__ import annotations

import pandas as pd

from copilot.detectors.market_structure import detect_market_structure
from copilot.detectors.liquidity import detect_liquidity


TOOL_SCHEMA = {
    "name": "check_cd_divergence_at_structure",
    "description": (
        "Detect Cumulative Delta divergence occurring at a key structural level "
        "(last swing high or swing low). "
        "Bearish: price at/near swing high but CD is falling (sellers absorbing). "
        "Bullish: price at/near swing low but CD is rising (buyers absorbing). "
        "Optionally checks whether a liquidity sweep preceded the divergence. "
        "Use to confirm or dispute a reversal signal at a POI — requires delta data "
        "(Binance klines)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol":        {"type": "string"},
            "timeframe":     {"type": "string", "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"]},
            "bars":          {"type": "integer", "default": 200},
            "proximity_atr": {
                "type": "number", "default": 0.5,
                "description": (
                    "How close (in ATR multiples) price must be to the swing level "
                    "to count as 'at structure'"
                ),
            },
            "div_lookback":  {
                "type": "integer", "default": 10,
                "description": "Bars to scan for divergence relative to current bar",
            },
            "require_sweep": {
                "type": "boolean", "default": False,
                "description": (
                    "If True, signal_strength can only be 'strong' when a sweep "
                    "preceded the divergence"
                ),
            },
        },
        "required": ["symbol", "timeframe"],
    },
}


def check_cd_divergence_at_structure(
    df: pd.DataFrame,
    proximity_atr: float = 0.5,
    div_lookback: int = 10,
    require_sweep: bool = False,
) -> dict:
    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------
    if len(df) < 20:
        return {
            "status": "insufficient_data",
            "divergence_detected": False,
            "reason": f"need >=20 bars, got {len(df)}",
        }
    if "delta" not in df.columns:
        return {
            "status": "insufficient_data",
            "divergence_detected": False,
            "reason": "missing delta column — use fetch_ohlcv_with_delta",
        }

    # ------------------------------------------------------------------
    # ATR (true range)
    # ------------------------------------------------------------------
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    if pd.isna(atr) or atr < 1e-10:
        atr = float(tr.mean())
    if atr < 1e-10:
        atr = 1e-10  # fully-flat market fallback

    # ------------------------------------------------------------------
    # Market structure — extract swing levels
    # ------------------------------------------------------------------
    ms = detect_market_structure(df)
    if "status" in ms:
        return {
            "divergence_detected": False,
            "type": "none",
            "at_structure": False,
            "structure_level": None,
            "structure_type": None,
            "proximity_to_level_atr": None,
            "sweep_preceded": False,
            "sweep_ts": None,
            "signal_strength": "none",
            "cd_divergence_detail": None,
            "reason": "market_structure_insufficient_data",
        }

    swing_high = ms.get("last_swing_high")
    swing_low = ms.get("last_swing_low")
    if swing_high is None or swing_low is None:
        return {
            "divergence_detected": False,
            "type": "none",
            "at_structure": False,
            "structure_level": None,
            "structure_type": None,
            "proximity_to_level_atr": None,
            "sweep_preceded": False,
            "sweep_ts": None,
            "signal_strength": "none",
            "cd_divergence_detail": None,
            "reason": "no_swings",
        }

    swing_high_price = float(swing_high["price"])
    swing_low_price = float(swing_low["price"])

    # ------------------------------------------------------------------
    # Proximity booleans
    # ------------------------------------------------------------------
    current_price = float(df["close"].iloc[-1])
    tolerance = proximity_atr * atr
    near_high = abs(current_price - swing_high_price) <= tolerance
    near_low = abs(current_price - swing_low_price) <= tolerance

    # ------------------------------------------------------------------
    # CD divergence — inlined from cumulative_delta._detect_divergences
    # ------------------------------------------------------------------
    cd = df["delta"].cumsum()
    divergences: list[dict] = []
    n = min(div_lookback, len(df) - 2)

    for lag in range(2, n + 1):
        curr_high = float(df["high"].iloc[-1])
        prev_high = float(df["high"].iloc[-lag])
        curr_low = float(df["low"].iloc[-1])
        prev_low = float(df["low"].iloc[-lag])
        curr_cd = float(cd.iloc[-1])
        prev_cd = float(cd.iloc[-lag])

        # Bearish: price higher high but CD lower
        if curr_high > prev_high and curr_cd < prev_cd and not divergences:
            divergences.append({
                "type": "bearish",
                "price_high": round(curr_high, 2),
                "cd_at_high": round(curr_cd, 4),
                "bar_ts": df.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "context": "price_new_high_cd_falling",
            })
            break

        # Bullish: price lower low but CD higher
        if curr_low < prev_low and curr_cd > prev_cd and not divergences:
            divergences.append({
                "type": "bullish",
                "price_low": round(curr_low, 2),
                "cd_at_low": round(curr_cd, 4),
                "bar_ts": df.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "context": "price_new_low_cd_rising",
            })
            break

    # ------------------------------------------------------------------
    # Match divergence direction to structure
    # ------------------------------------------------------------------
    matched_divergence = None
    at_structure = False
    structure_level = None
    structure_type = None

    for div in divergences:
        if div["type"] == "bearish" and near_high:
            matched_divergence = div
            at_structure = True
            structure_level = swing_high_price
            structure_type = "swing_high"
            break
        if div["type"] == "bullish" and near_low:
            matched_divergence = div
            at_structure = True
            structure_level = swing_low_price
            structure_type = "swing_low"
            break
        # Divergence exists but not at a structural level → weak signal
        matched_divergence = div

    # ------------------------------------------------------------------
    # Proximity metric
    # ------------------------------------------------------------------
    if matched_divergence is not None and structure_level is not None:
        proximity_to_level_atr = round(
            abs(current_price - structure_level) / atr, 3
        )
    elif matched_divergence is not None:
        proximity_to_level_atr = round(
            min(
                abs(current_price - swing_high_price),
                abs(current_price - swing_low_price),
            ) / atr,
            3,
        )
    else:
        proximity_to_level_atr = None

    # ------------------------------------------------------------------
    # Sweep check (only when a divergence was found or require_sweep)
    # ------------------------------------------------------------------
    sweep_preceded = False
    sweep_ts: str | None = None
    if matched_divergence is not None or require_sweep:
        liq = detect_liquidity(df)
        sweeps = liq.get("recent_sweeps", [])
        if sweeps:
            sweep_preceded = True
            sweep_ts = sweeps[0].get("sweep_ts")

    # ------------------------------------------------------------------
    # Signal strength + require_sweep gate
    # ------------------------------------------------------------------
    divergence_detected = matched_divergence is not None

    if require_sweep and not sweep_preceded:
        divergence_detected = False
        signal_strength = "none"
    elif matched_divergence is None:
        signal_strength = "none"
    elif at_structure and sweep_preceded:
        signal_strength = "strong"
    elif at_structure:
        signal_strength = "moderate"
    else:
        signal_strength = "weak"

    return {
        "divergence_detected": divergence_detected,
        "type": matched_divergence["type"] if matched_divergence else "none",
        "at_structure": at_structure,
        "structure_level": structure_level,
        "structure_type": structure_type,
        "proximity_to_level_atr": proximity_to_level_atr,
        "sweep_preceded": sweep_preceded,
        "sweep_ts": sweep_ts,
        "signal_strength": signal_strength,
        "cd_divergence_detail": matched_divergence,
    }
