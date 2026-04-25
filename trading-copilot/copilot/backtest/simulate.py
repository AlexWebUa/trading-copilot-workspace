"""
Exit simulation and entry/SL/TP resolution.

All functions are pure (no I/O, no side effects) — easy to unit-test.

simulated_exit   — scan future bars for first wick touch of TP or SL
resolve_entry    — compute actual entry price based on entry_after mode
resolve_sl       — compute stop-loss price from sl_logic string
resolve_tp       — compute take-profit price from tp_logic string
"""

from __future__ import annotations

import pandas as pd

# Sentinel returned by resolve_entry when still waiting for limit fill
_WAITING = ...


# ---------------------------------------------------------------------------
# Exit simulation
# ---------------------------------------------------------------------------

def simulated_exit(
    direction: str,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    future_bars: pd.DataFrame,
) -> tuple[str | None, float | None, str | None]:
    """
    Scan future_bars for the first bar that wicks into TP or SL.

    Same-bar conflict (both TP and SL hit on the same bar) → SL wins.
    This is the conservative convention for OHLCV-based backtesting where
    intra-bar wick order is unknowable.

    Returns:
        (result, exit_price, exit_ts) where result is "win" | "loss" | None
        None → trade still open at end of future_bars (pending).
    """
    for i in range(len(future_bars)):
        bar = future_bars.iloc[i]
        bar_ts = future_bars.index[i].strftime("%Y-%m-%dT%H:%M:%SZ")
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])

        if direction == "long":
            sl_hit = bar_low <= sl_price
            tp_hit = bar_high >= tp_price
        else:  # short
            sl_hit = bar_high >= sl_price
            tp_hit = bar_low <= tp_price

        if sl_hit:
            # SL wins even if TP also touched (same-bar conservative rule)
            return "loss", sl_price, bar_ts
        if tp_hit:
            return "win", tp_price, bar_ts

    return None, None, None


# ---------------------------------------------------------------------------
# Entry resolution
# ---------------------------------------------------------------------------

def resolve_entry(
    entry_after: str,
    signal_bar_idx: int,
    current_bar_idx: int,
    df: pd.DataFrame,
    detector_cache: dict,
    max_wait_bars: int = 10,
) -> float | None:
    """
    Compute the actual entry price (or None/Ellipsis) based on entry_after mode.

    Returns:
        float       — entry price (enter at this bar)
        None        — signal cancelled (timeout or missing data)
        ... (Ellipsis) — still waiting, caller should continue to next bar

    entry_after modes:
      "next_open"    — returns open of bar signal_bar_idx+1 (available after 1 bar)
      "signal_close" — returns close of signal bar (immediate, no waiting)
      "fvg_ce"       — scans forward for a bar that touches FVG 50% midpoint
      "ob_midpoint"  — scans forward for a bar that touches OB midpoint
    """
    if entry_after == "signal_close":
        return float(df.iloc[signal_bar_idx]["close"])

    if entry_after == "next_open":
        target_idx = signal_bar_idx + 1
        if current_bar_idx < target_idx:
            return _WAITING
        if target_idx >= len(df):
            return None
        return float(df.iloc[target_idx]["open"])

    if entry_after == "fvg_ce":
        return _scan_for_level(
            "fvg_ce",
            signal_bar_idx=signal_bar_idx,
            current_bar_idx=current_bar_idx,
            df=df,
            detector_cache=detector_cache,
            max_wait_bars=max_wait_bars,
        )

    if entry_after == "ob_midpoint":
        return _scan_for_level(
            "ob_midpoint",
            signal_bar_idx=signal_bar_idx,
            current_bar_idx=current_bar_idx,
            df=df,
            detector_cache=detector_cache,
            max_wait_bars=max_wait_bars,
        )

    # Unknown mode — fall back to next_open
    target_idx = signal_bar_idx + 1
    if current_bar_idx < target_idx:
        return _WAITING
    if target_idx >= len(df):
        return None
    return float(df.iloc[target_idx]["open"])


def _scan_for_level(
    mode: str,
    signal_bar_idx: int,
    current_bar_idx: int,
    df: pd.DataFrame,
    detector_cache: dict,
    max_wait_bars: int,
) -> float | None:
    """
    Scan bars after the signal bar, looking for a wick that touches the target level.
    The target level is the FVG CE (mode="fvg_ce") or OB midpoint (mode="ob_midpoint").

    Returns float if the current bar touches the level, _WAITING if not yet reached,
    or None if the window expired or the level cannot be resolved.
    """
    # Resolve the target price from cached detector results
    level = _resolve_limit_level(mode, detector_cache)
    if level is None:
        return None  # can't determine level → cancel

    bars_elapsed = current_bar_idx - signal_bar_idx
    if bars_elapsed > max_wait_bars:
        return None  # window expired → cancel

    if bars_elapsed < 1:
        return _WAITING  # signal just fired, need at least 1 bar

    # Check if current bar touches the level (wick)
    bar = df.iloc[current_bar_idx]
    bar_low = float(bar["low"])
    bar_high = float(bar["high"])

    # For long setups, FVG/OB is below → price retraces down to level
    # For short setups, FVG/OB is above → price retraces up to level
    # Since we don't know direction here, accept touch from either side
    if bar_low <= level <= bar_high:
        return level

    return _WAITING


def _resolve_limit_level(mode: str, detector_cache: dict) -> float | None:
    """Extract the limit entry price from cached detector results."""
    if mode == "fvg_ce":
        fvg_result = detector_cache.get("detect_fvg")
        if not fvg_result:
            return None
        fvgs = fvg_result.get("fvgs", [])
        if not fvgs:
            return None
        fvg = fvgs[0]
        upper = fvg.get("upper")
        lower = fvg.get("lower")
        if upper is None or lower is None:
            return None
        return (float(upper) + float(lower)) / 2.0

    if mode == "ob_midpoint":
        ob_result = detector_cache.get("detect_order_block")
        if not ob_result:
            return None
        obs = ob_result.get("obs", [])
        if not obs:
            return None
        ob = obs[0]
        high = ob.get("high") or ob.get("upper")
        low = ob.get("low") or ob.get("lower")
        if high is None or low is None:
            return None
        return (float(high) + float(low)) / 2.0

    return None


# ---------------------------------------------------------------------------
# SL resolution
# ---------------------------------------------------------------------------

def resolve_sl(
    sl_logic: str,
    entry_price: float,
    direction: str,
    slice_df: pd.DataFrame,
    detector_cache: dict,
) -> float:
    """
    Compute stop-loss price from sl_logic string.

    sl_logic options:
      "atr:N"  — entry ± ATR(14) * N
      "pct:N"  — entry ± entry * (N/100)
      "swing"  — below/above last intact fractal swing (from detect_fractals)
      "ob"     — below/above detected OB boundary
      "fvg"    — below/above FVG zone boundary

    Falls back to "atr:1.5" if structural SL cannot be resolved.
    """
    atr = _compute_atr(slice_df)
    sign = -1 if direction == "long" else 1  # long: SL below entry; short: SL above

    if sl_logic.startswith("atr:"):
        try:
            multiplier = float(sl_logic.split(":")[1])
        except (IndexError, ValueError):
            multiplier = 1.5
        return entry_price + sign * atr * multiplier

    if sl_logic.startswith("pct:"):
        try:
            pct = float(sl_logic.split(":")[1])
        except (IndexError, ValueError):
            pct = 1.0
        return entry_price * (1.0 + sign * pct / 100.0)

    if sl_logic == "swing":
        return _sl_from_swing(entry_price, direction, slice_df, detector_cache, atr)

    if sl_logic == "ob":
        return _sl_from_ob(entry_price, direction, detector_cache, atr)

    if sl_logic == "fvg":
        return _sl_from_fvg(entry_price, direction, detector_cache, atr)

    # Unknown mode → fallback
    return entry_price + sign * atr * 1.5


def _sl_from_swing(
    entry_price: float,
    direction: str,
    slice_df: pd.DataFrame,
    detector_cache: dict,
    atr: float,
) -> float:
    """SL below/above the most recent intact fractal swing."""
    sign = -1 if direction == "long" else 1
    buffer = atr * 0.1

    fractal_result = detector_cache.get("detect_fractals")
    if fractal_result:
        # detect_fractals returns recent fractals sorted newest-first
        fractals = fractal_result.get("fractals", [])
        for f in fractals:
            if direction == "long" and f.get("type") == "low" and not f.get("is_swept", False):
                price = f.get("price")
                if price and price < entry_price:
                    return float(price) - buffer
            if direction == "short" and f.get("type") == "high" and not f.get("is_swept", False):
                price = f.get("price")
                if price and price > entry_price:
                    return float(price) + buffer

    # Fallback: use recent swing low/high from OHLCV
    lookback = min(20, len(slice_df))
    recent = slice_df.iloc[-lookback:]
    if direction == "long":
        swing = float(recent["low"].min())
        return swing - buffer
    else:
        swing = float(recent["high"].max())
        return swing + buffer


def _sl_from_ob(
    entry_price: float,
    direction: str,
    detector_cache: dict,
    atr: float,
) -> float:
    """SL below/above the first OB in cached results. Fallback: atr:1.5."""
    sign = -1 if direction == "long" else 1
    buffer = atr * 0.05

    ob_result = detector_cache.get("detect_order_block")
    if ob_result:
        obs = ob_result.get("obs", [])
        if obs:
            ob = obs[0]
            if direction == "long":
                low = ob.get("low") or ob.get("lower")
                if low is not None:
                    return float(low) - buffer
            else:
                high = ob.get("high") or ob.get("upper")
                if high is not None:
                    return float(high) + buffer

    return entry_price + sign * atr * 1.5


def _sl_from_fvg(
    entry_price: float,
    direction: str,
    detector_cache: dict,
    atr: float,
) -> float:
    """SL below/above the first FVG zone. Fallback: atr:1.5."""
    sign = -1 if direction == "long" else 1
    buffer = atr * 0.05

    fvg_result = detector_cache.get("detect_fvg")
    if fvg_result:
        fvgs = fvg_result.get("fvgs", [])
        if fvgs:
            fvg = fvgs[0]
            if direction == "long":
                lower = fvg.get("lower")
                if lower is not None:
                    return float(lower) - buffer
            else:
                upper = fvg.get("upper")
                if upper is not None:
                    return float(upper) + buffer

    return entry_price + sign * atr * 1.5


# ---------------------------------------------------------------------------
# TP resolution
# ---------------------------------------------------------------------------

def resolve_tp(
    tp_logic: str,
    entry_price: float,
    sl_price: float,
    direction: str,
    slice_df: pd.DataFrame,
    detector_cache: dict,
) -> float:
    """
    Compute take-profit price from tp_logic string.

    tp_logic options:
      "rr:N"       — entry ± risk * N (always works)
      "liquidity"  — nearest unswept liquidity pool above/below
      "next_hvn"   — nearest High Volume Node above/below (from volume_profile)

    Falls back to "rr:2.0" if structural TP cannot be resolved.
    """
    risk = abs(entry_price - sl_price)
    sign = 1 if direction == "long" else -1

    if tp_logic.startswith("rr:"):
        try:
            ratio = float(tp_logic.split(":")[1])
        except (IndexError, ValueError):
            ratio = 2.0
        return entry_price + sign * risk * ratio

    if tp_logic == "liquidity":
        tp = _tp_from_liquidity(entry_price, direction, detector_cache)
        if tp is not None:
            return tp
        # fallback
        return entry_price + sign * risk * 2.0

    if tp_logic == "next_hvn":
        tp = _tp_from_hvn(entry_price, direction, detector_cache, slice_df)
        if tp is not None:
            return tp
        return entry_price + sign * risk * 2.0

    # Unknown → fallback
    return entry_price + sign * risk * 2.0


def _tp_from_liquidity(
    entry_price: float,
    direction: str,
    detector_cache: dict,
) -> float | None:
    """TP at nearest unswept buyside/sellside liquidity pool."""
    liq_result = detector_cache.get("detect_liquidity")
    if not liq_result:
        return None

    if direction == "long":
        pools = liq_result.get("buyside_liquidity", [])
        candidates = [
            p["price"] for p in pools
            if isinstance(p, dict) and p.get("price", 0) > entry_price
        ]
        return float(min(candidates)) if candidates else None
    else:
        pools = liq_result.get("sellside_liquidity", [])
        candidates = [
            p["price"] for p in pools
            if isinstance(p, dict) and p.get("price", 0) < entry_price
        ]
        return float(max(candidates)) if candidates else None


def _tp_from_hvn(
    entry_price: float,
    direction: str,
    detector_cache: dict,
    slice_df: pd.DataFrame,
) -> float | None:
    """TP at nearest HVN above/below from volume profile."""
    from copilot.detectors.volume_profile import detect_volume_profile

    vp_result = detector_cache.get("detect_volume_profile")
    if not vp_result:
        # Call it if not already cached
        try:
            vp_result = detect_volume_profile(slice_df)
            detector_cache["detect_volume_profile"] = vp_result
        except Exception:
            return None

    if direction == "long":
        nearest = vp_result.get("nearest_hvn_above")
    else:
        nearest = vp_result.get("nearest_hvn_below")

    if nearest and nearest.get("price_mid"):
        return float(nearest["price_mid"])
    return None


# ---------------------------------------------------------------------------
# ATR helper
# ---------------------------------------------------------------------------

def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Return ATR(period) from a OHLCV DataFrame slice. Minimum 1 period."""
    if len(df) < 2:
        return float(df["high"].iloc[-1] - df["low"].iloc[-1]) if len(df) == 1 else 1.0
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    rolling = tr.rolling(period).mean().iloc[-1]
    result = float(rolling) if pd.notna(rolling) else float(tr.mean())
    return result if result > 0 else 1.0
