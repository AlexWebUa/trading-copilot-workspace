"""
Orderflow composite meta-detectors — Phase 6.

These detectors synthesize two existing sub-detectors into a combined
contextual check. They are pure OHLCV (no delta columns required) and
auto-discovered by build_detector_registry() alongside all other detectors.

  check_ob_in_hvn        — OB price range overlaps ≥ N% with any HVN node
  check_poc_location     — current price location relative to POC (discount/premium)
  check_price_in_lvn     — current close is inside a thin-volume (LVN) node
  check_cd_absorption    — high-volume, small-range, close-near-high bar (hidden buyers)
                           OHLCV proxy for footprint imbalance; does NOT call CD detector.
"""

from __future__ import annotations

import pandas as pd

from copilot.detectors.order_block import detect_order_block
from copilot.detectors.volume_profile import detect_volume_profile


# ---------------------------------------------------------------------------
# check_ob_in_hvn
# ---------------------------------------------------------------------------

def check_ob_in_hvn(
    df: pd.DataFrame,
    min_overlap_pct: float = 50.0,
    **kwargs,
) -> dict:
    """
    Check if the most recent unmitigated bullish OB price range overlaps
    ≥ min_overlap_pct% of its body with any HVN node.

    Returns:
        {
            in_hvn: bool,
            overlap_pct: float,          # 0.0 if no OB or no HVN
            hvn_price_mid: float | None, # mid of matching HVN, or None
        }
    """
    ob_result = detect_order_block(df, **kwargs)
    if ob_result.get("status") == "insufficient_data" or not ob_result.get("obs"):
        return {"in_hvn": False, "overlap_pct": 0.0, "hvn_price_mid": None}

    vp_result = detect_volume_profile(df)
    if vp_result.get("status") in ("insufficient_data", "flat_market", "no_volume"):
        return {"in_hvn": False, "overlap_pct": 0.0, "hvn_price_mid": None}

    hvn_nodes: list[dict] = vp_result.get("hvn_nodes", [])
    if not hvn_nodes:
        return {"in_hvn": False, "overlap_pct": 0.0, "hvn_price_mid": None}

    # Use first unmitigated OB
    target_ob = None
    for ob in ob_result["obs"]:
        if not ob.get("is_mitigated", True):
            target_ob = ob
            break

    if target_ob is None:
        # Fallback: use first OB regardless
        target_ob = ob_result["obs"][0]

    ob_low = float(target_ob.get("low", 0.0))
    ob_high = float(target_ob.get("high", ob_low))
    ob_body = ob_high - ob_low

    if ob_body < 1e-10:
        return {"in_hvn": False, "overlap_pct": 0.0, "hvn_price_mid": None}

    best_overlap = 0.0
    best_hvn_mid = None

    for node in hvn_nodes:
        node_lo = float(node.get("price_low", 0.0))
        node_hi = float(node.get("price_high", 0.0))

        overlap = min(ob_high, node_hi) - max(ob_low, node_lo)
        if overlap <= 0:
            continue

        # Overlap as % of OB body
        pct = round(overlap / ob_body * 100.0, 2)
        if pct > best_overlap:
            best_overlap = pct
            best_hvn_mid = float(node.get("price_mid", (node_lo + node_hi) / 2))

    in_hvn = best_overlap >= min_overlap_pct
    return {
        "in_hvn": in_hvn,
        "overlap_pct": best_overlap,
        "hvn_price_mid": best_hvn_mid if in_hvn else None,
    }


# ---------------------------------------------------------------------------
# check_poc_location
# ---------------------------------------------------------------------------

def check_poc_location(df: pd.DataFrame, **kwargs) -> dict:
    """
    Return current price location relative to the Volume Profile POC.

    Returns:
        {
            location: str,      # "above_poc" | "below_poc" | "at_poc"
            poc: float,
            in_discount: bool,  # price below POC
            in_premium: bool,   # price above POC
        }
    """
    vp_result = detect_volume_profile(df, **kwargs)
    if vp_result.get("status") in ("insufficient_data", "flat_market", "no_volume"):
        # Graceful fallback — return neutral state, never crash
        current = float(df["close"].iloc[-1]) if len(df) > 0 else 0.0
        return {
            "location": "unknown",
            "poc": current,
            "in_discount": False,
            "in_premium": False,
        }

    poc = float(vp_result.get("poc", 0.0))
    location = vp_result.get("current_price_location", "at_poc")
    current_price = float(vp_result.get("current_price", 0.0))

    return {
        "location": location,
        "poc": poc,
        "in_discount": current_price < poc,
        "in_premium": current_price > poc,
    }


# ---------------------------------------------------------------------------
# check_price_in_lvn
# ---------------------------------------------------------------------------

def check_price_in_lvn(df: pd.DataFrame, **kwargs) -> dict:
    """
    Check if the current close price is inside any LVN (Low Volume Node) range.

    Returns:
        {
            in_lvn: bool,
            node: dict | None,  # the matching LVN node (price_low/high/mid/volume_pct)
        }
    """
    if len(df) < 10:
        return {"in_lvn": False, "node": None}

    current_price = float(df["close"].iloc[-1])
    vp_result = detect_volume_profile(df, **kwargs)

    if vp_result.get("status") in ("insufficient_data", "flat_market", "no_volume"):
        return {"in_lvn": False, "node": None}

    lvn_nodes: list[dict] = vp_result.get("lvn_nodes", [])
    for node in lvn_nodes:
        lo = float(node.get("price_low", 0.0))
        hi = float(node.get("price_high", 0.0))
        if lo <= current_price <= hi:
            return {"in_lvn": True, "node": node}

    return {"in_lvn": False, "node": None}


# ---------------------------------------------------------------------------
# check_cd_absorption
# ---------------------------------------------------------------------------

def check_cd_absorption(
    df: pd.DataFrame,
    min_volume_pct: float = 70.0,
    max_range_atr: float = 0.5,
    **kwargs,
) -> dict:
    """
    Detect absorption bar on the LAST bar: high volume + small price range +
    close near the high (bullish hidden buyers absorbing supply).

    This is a pure OHLCV proxy for footprint imbalance — no delta columns
    required. It does NOT call detect_cumulative_delta.

    Args:
        min_volume_pct: volume of last bar must exceed avg_volume * (this/100)
        max_range_atr:  range of last bar must be < ATR(14) * this

    Returns:
        {
            absorption_detected: bool,
            vol_ratio: float,       # last_bar_vol / avg_vol
            range_atr_ratio: float, # last_bar_range / ATR(14)
            close_position: float,  # (close - low) / (high - low); 1.0 = close at high
        }
    """
    if len(df) < 14:
        return {
            "absorption_detected": False,
            "vol_ratio": 0.0,
            "range_atr_ratio": 0.0,
            "close_position": 0.0,
        }

    last = df.iloc[-1]
    high = float(last["high"])
    low = float(last["low"])
    close = float(last["close"])
    volume = float(last["volume"])

    bar_range = high - low

    # ATR(14) on prior bars to avoid self-contamination
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr_val = float(tr.rolling(14).mean().iloc[-1])
    if pd.isna(atr_val) or atr_val < 1e-10:
        atr_val = float(tr.mean())

    # Average volume over the whole window (excluding last bar avoids recency bias)
    avg_vol = float(df["volume"].iloc[:-1].mean()) if len(df) > 1 else float(df["volume"].mean())
    if avg_vol < 1e-10:
        avg_vol = 1e-10

    vol_ratio = round(volume / avg_vol, 3)
    range_atr_ratio = round(bar_range / atr_val, 3) if atr_val > 1e-10 else 99.9

    # Close position in bar range (0 = at low, 1 = at high)
    close_position = round((close - low) / bar_range, 3) if bar_range > 1e-10 else 0.5

    # Conditions: volume above threshold + range below threshold + close in upper half
    high_volume = vol_ratio >= (min_volume_pct / 100.0)
    small_range = range_atr_ratio <= max_range_atr
    close_near_high = close_position >= 0.6  # close in upper 40% of bar

    return {
        "absorption_detected": high_volume and small_range and close_near_high,
        "vol_ratio": vol_ratio,
        "range_atr_ratio": range_atr_ratio,
        "close_position": close_position,
    }
