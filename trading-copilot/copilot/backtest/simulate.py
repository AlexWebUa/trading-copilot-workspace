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
    direction: str | None = None,
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
            direction=direction,
        )

    if entry_after == "ob_midpoint":
        return _scan_for_level(
            "ob_midpoint",
            signal_bar_idx=signal_bar_idx,
            current_bar_idx=current_bar_idx,
            df=df,
            detector_cache=detector_cache,
            max_wait_bars=max_wait_bars,
            direction=direction,
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
    direction: str | None = None,
) -> float | None:
    """
    Scan bars after the signal bar, looking for a wick that touches the target level.
    The target level is the FVG CE (mode="fvg_ce") or OB midpoint (mode="ob_midpoint").

    Returns float if the current bar touches the level, _WAITING if not yet reached,
    or None if the window expired or the level cannot be resolved.
    """
    # Resolve the target price from cached detector results
    level = _resolve_limit_level(mode, detector_cache, direction)
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


def _resolve_limit_level(
    mode: str,
    detector_cache: dict,
    direction: str | None = None,
) -> float | None:
    """Extract the limit entry price from cached detector results.

    P0-6: when direction is known, only zones of the matching polarity are
    considered — a long must not fill at a bearish FVG/OB midpoint.
    """
    want_type = {"long": "bullish", "short": "bearish"}.get(direction or "")

    if mode == "fvg_ce":
        fvg_result = detector_cache.get("detect_fvg")
        if not fvg_result:
            return None
        fvgs = [
            f for f in fvg_result.get("fvgs", [])
            if want_type is None or f.get("type") == want_type
        ]
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
        obs = [
            o for o in ob_result.get("obs", [])
            if want_type is None or o.get("type") == want_type
        ]
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

    if sl_logic == "sweep_fractal":
        return _sl_from_sweep_fractal(entry_price, direction, slice_df, detector_cache, atr)

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
            if direction == "long" and f.get("type") == "swing_low" and not f.get("is_swept", False):
                price = f.get("price")
                if price and price < entry_price:
                    return float(price) - buffer
            if direction == "short" and f.get("type") == "swing_high" and not f.get("is_swept", False):
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
    min_rr: float = 1.8,
    registry: dict | None = None,
) -> float | None:
    """
    Compute take-profit price from tp_logic string.

    tp_logic options:
      "rr:N"             — entry ± risk * N (always works)
      "liquidity"        — nearest unswept liquidity pool above/below
      "next_hvn"         — nearest High Volume Node above/below
      "fractal_or_fta"   — the 1h3m target rule: nearest fractal that pays
                           min_rr; if a counter-trend POI (FTA) blocks the path
                           before it, take exactly min_rr inside the FTA instead.
                           None when neither is reachable → skip the setup.
      "fta_or_skip"      — nearest counter-trend POI (FVG/OB/breaker/mitigation)
                           between entry and the liquidity draw. TP goes at its
                           near edge if that still pays `min_rr`; otherwise the
                           trade is not taken (returns None).
      "fta_or_liquidity" — same, but an FTA too close to pay is ignored and the
                           liquidity pool behind it becomes the target.

    The two FTA variants exist to answer an open question of the trader's
    methodology — whether an obstacle sitting too close is a reason to skip the
    trade or merely something to trade through. They differ only here, so a
    backtest can measure it.

    Returns None only for "fta_or_skip"; callers treat None as "skip this setup".
    Falls back to "rr:2.0" if a structural TP cannot be resolved.
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

    if tp_logic == "nearest_fractal":
        return _tp_nearest_fractal(
            entry_price, sl_price, direction, slice_df, detector_cache, registry, min_rr
        )

    if tp_logic in ("fractal_or_fta", "fractal_or_fta_soft"):
        return _tp_fractal_or_fta(
            entry_price, sl_price, direction, slice_df, detector_cache, registry, min_rr,
            ignore_near_fta=(tp_logic == "fractal_or_fta_soft"),
        )

    if tp_logic in ("fta_or_skip", "fta_or_liquidity"):
        fta = _tp_from_fta(entry_price, direction, detector_cache, slice_df, registry)
        if fta is not None:
            rr = abs(fta - entry_price) / risk if risk > 0 else 0.0
            if rr >= min_rr:
                return fta
            if tp_logic == "fta_or_skip":
                return None
        # No FTA in the way, or it was too close and we chose to trade through it.
        beyond = _tp_from_liquidity(entry_price, direction, detector_cache)
        if beyond is not None:
            return beyond
        return None if tp_logic == "fta_or_skip" else entry_price + sign * risk * 2.0

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


# ---------------------------------------------------------------------------
# FTA — First Trouble Area
# ---------------------------------------------------------------------------

# Counter-trend zones that count as an obstacle, and how to read each one's
# bounds out of its detector result. The trader's definition (Aug 2026): "FTA
# includes counter-trend POI — FVG, OB, and their derivatives."
_FTA_SOURCES: tuple[tuple[str, str, str, str], ...] = (
    # (detector, list field, upper-bound key, lower-bound key)
    ("detect_fvg", "fvgs", "upper", "lower"),
    ("detect_ifvg", "ifvgs", "upper", "lower"),
    ("detect_order_block", "obs", "high", "low"),
    ("detect_breaker_block", "breakers", "high", "low"),
    ("detect_mitigation_block", "blocks", "high", "low"),
)


def _fta_zone_is_counter(zone: dict, direction: str) -> bool:
    """A long is obstructed by bearish zones, a short by bullish ones."""
    ztype = str(zone.get("type", "")).lower()
    if not ztype:
        return True  # untyped zone — treat as an obstacle rather than ignore it
    return ("bear" in ztype) if direction == "long" else ("bull" in ztype)


def _tp_from_fta(
    entry_price: float,
    direction: str,
    detector_cache: dict,
    slice_df: pd.DataFrame,
    registry: dict | None,
) -> float | None:
    """Near edge of the closest counter-trend POI in front of the trade.

    "Near edge" is where price first enters the zone — the bottom of a zone
    above a long, the top of a zone below a short. Targeting the far side would
    assume the obstacle gets fully consumed, which is exactly what it might not do.
    """
    edges: list[float] = []

    for detector, list_field, hi_key, lo_key in _FTA_SOURCES:
        result = detector_cache.get(detector)
        if result is None and registry is not None:
            fn = registry.get(detector)
            if fn is None:
                continue
            try:
                result = fn(slice_df)
            except Exception:
                continue
            detector_cache[detector] = result
        if not isinstance(result, dict):
            continue

        for zone in result.get(list_field) or []:
            if not isinstance(zone, dict):
                continue
            if zone.get("is_mitigated") or zone.get("fill_state") == "filled":
                continue
            if not _fta_zone_is_counter(zone, direction):
                continue
            hi, lo = zone.get(hi_key), zone.get(lo_key)
            if hi is None or lo is None:
                continue
            near = float(lo) if direction == "long" else float(hi)
            if direction == "long" and near > entry_price:
                edges.append(near)
            elif direction == "short" and near < entry_price:
                edges.append(near)

    if not edges:
        return None
    return min(edges) if direction == "long" else max(edges)


def _sl_from_sweep_fractal(
    entry_price: float,
    direction: str,
    slice_df: pd.DataFrame,
    detector_cache: dict,
    atr: float,
) -> float:
    """Stop behind the fractal that took the liquidity.

    The trader's own placement (validated against the 1 Aug example: sweep at
    21:00 Kyiv, stop 62275 = the low of the 03:30-later 3M fractal). The
    previous "swing" mode put the stop behind an HOURLY swing while the entry
    was made on 3M, inflating risk until most setups failed the 1.8R floor.

    Falls back to the swept level itself, then to an ATR stop, so a missing
    sweep record degrades instead of raising.
    """
    sign = -1 if direction == "long" else 1
    buffer = atr * 0.1

    liq = detector_cache.get("detect_liquidity") or {}
    sweeps = liq.get("recent_sweeps") or []
    if sweeps:
        sweep = sweeps[0]
        ts = sweep.get("sweep_ts")
        # The sweep bar's own extreme is the fractal that did the taking.
        if ts is not None:
            try:
                bar = slice_df.loc[pd.Timestamp(ts)]
                extreme = float(bar["low"]) if direction == "long" else float(bar["high"])
                return extreme + sign * buffer
            except (KeyError, TypeError, ValueError):
                pass
        level = sweep.get("swept_level")
        if level is not None:
            return float(level) + sign * buffer

    return entry_price + sign * atr * 1.5



# Silver Bullet targets are "low hanging fruit" — the nearest opposing pool,
# deliberately not stretched. Taken literally the nearest fractal is often
# unreachable at min_rr (on the trader's 11-Aug example the nearest three paid
# 0.74R / 0.97R / 1.02R against a 1.3 floor), and since min_rr is a hard gate on
# opening a trade at all, the operative rule is "the nearest one that pays".
#
# max_results is raised well above the detector's default of 10: on 15m that
# default spans only a few hours, and the trader's own pool on 11 Aug (63863.9)
# fell outside it.
_FRACTAL_TARGET_POOL = 60


def _tp_nearest_fractal(
    entry_price: float,
    sl_price: float,
    direction: str,
    slice_df: pd.DataFrame,
    detector_cache: dict,
    registry: dict | None,
    min_rr: float,
) -> float | None:
    """Nearest unbroken 3-candle fractal beyond entry that pays min_rr."""
    risk = abs(entry_price - sl_price)
    if risk <= 0:
        return None

    cache_key = f"detect_fractals_3_{_FRACTAL_TARGET_POOL}"
    fractals = detector_cache.get(cache_key)
    if fractals is None and registry is not None:
        fn = registry.get("detect_fractals")
        if fn is not None:
            try:
                fractals = fn(slice_df, bars="3", max_results=_FRACTAL_TARGET_POOL)
                detector_cache[cache_key] = fractals
            except Exception:
                fractals = None

    want = "swing_high" if direction == "long" else "swing_low"
    levels = sorted(
        (
            float(f["price"])
            for f in (fractals or {}).get("fractals", [])
            if f.get("price") is not None
            and not f.get("is_broken")
            and f.get("type") == want
            and (
                float(f["price"]) > entry_price if direction == "long"
                else float(f["price"]) < entry_price
            )
        ),
        reverse=direction == "short",
    )
    for level in levels:                      # already ordered nearest-first
        if abs(level - entry_price) / risk >= min_rr:
            return level
    return None

def _tp_fractal_or_fta(
    entry_price: float,
    sl_price: float,
    direction: str,
    slice_df: pd.DataFrame,
    detector_cache: dict,
    registry: dict | None,
    min_rr: float,
    ignore_near_fta: bool = False,
) -> float | None:
    """1h3m target rule (trader's spec, 2026-08-22).

    Targets are the **two nearest 3-candle fractals on the signal timeframe** —
    no further. An FTA (counter-trend POI) in front of a target replaces it:
    price is not expected to pass through the obstacle, so the trade is closed
    at the obstacle's **near edge**, whatever R that pays.

        FTA before the 1st fractal      → take the FTA (or skip if it pays < min_rr)
        1st fractal pays min_rr         → take it
        1st too close, FTA before 2nd   → take the FTA (or skip)
        1st too close, 2nd pays min_rr  → take the 2nd
        otherwise                       → skip

    Returns None when nothing reachable pays min_rr; the caller skips the setup.
    """
    risk = abs(entry_price - sl_price)
    if risk <= 0:
        return None

    def pays(level: float) -> bool:
        return abs(level - entry_price) / risk >= min_rr

    def beyond(level: float) -> bool:
        return level > entry_price if direction == "long" else level < entry_price

    def nearer(a: float, b: float) -> bool:
        """Is a closer to entry than b, in the direction of the trade?"""
        return a < b if direction == "long" else a > b

    # ── the two nearest 3-candle fractals on the signal timeframe ────────
    # max_results must be raised: the detector's default keeps the 10 most
    # RECENT fractals, while this rule wants the two nearest in PRICE. An older
    # but closer level simply fell out of the list, so the rule reached past it
    # to a further target — or skipped the trade. Measured on the run-2 window:
    # 11 of 41 target resolutions changed between the 10- and 60-fractal pools.
    cache_key = f"detect_fractals_3_{_FRACTAL_TARGET_POOL}"
    fractals = detector_cache.get(cache_key)
    if fractals is None and registry is not None:
        fn = registry.get("detect_fractals")
        if fn is not None:
            try:
                fractals = fn(slice_df, bars="3", max_results=_FRACTAL_TARGET_POOL)
                detector_cache[cache_key] = fractals
            except Exception:
                fractals = None

    levels = sorted(
        (
            float(f["price"])
            for f in (fractals or {}).get("fractals", [])
            if f.get("price") is not None
            and not f.get("is_broken")
            and beyond(float(f["price"]))
        ),
        reverse=direction == "short",
    )
    first = levels[0] if levels else None
    second = levels[1] if len(levels) > 1 else None

    fta = _tp_from_fta(entry_price, direction, detector_cache, slice_df, registry)

    # An FTA closer than min_rr is a wall the trade cannot be closed against.
    # Two readings of the trader's rule live side by side, because his own
    # reference trade contradicts the strict one:
    #   "fractal_or_fta"      — strict: any POI in front kills the setup. On 1H
    #       there is nearly always an FVG within a few dozen points, so this
    #       skipped 34% of signals and the validated 1-Aug trade too, which was
    #       vetoed by an imbalance 34 points above entry paying 0.16R.
    #   "fractal_or_fta_soft" — a POI that cannot pay min_rr is noise and is
    #       ignored, so an FTA can only pull the target NEARER, never veto the
    #       trade. This is "if the FTA is beyond 1.8R, take its near edge" read
    #       as "an FTA matters only from 1.8R onward".
    if ignore_near_fta and fta is not None and not pays(fta):
        fta = None

    # ── an obstacle in front of the first target replaces it outright ────
    if fta is not None and (first is None or nearer(fta, first)):
        return fta if pays(fta) else None

    if first is not None and pays(first):
        return first

    # First target too close: look one fractal further, but no further than that.
    if fta is not None and (second is None or nearer(fta, second)):
        return fta if pays(fta) else None

    if second is not None and pays(second):
        return second

    return None
