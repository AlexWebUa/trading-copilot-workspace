"""
Absorption at POI detector.

Checks whether the most recent bar shows institutional absorption
(high volume + small range + close near high) AND current price sits inside
an active Point of Interest (unmitigated OB or untouched/IOFED FVG).

Absorption at POI = hidden institutional accumulation/distribution before a
reversal. Use after price reaches a known OB or FVG zone. Does NOT require
delta data — pure OHLCV.
"""
from __future__ import annotations

import pandas as pd

from copilot.detectors.orderflow_composite import check_cd_absorption
from copilot.detectors.order_block import detect_order_block
from copilot.detectors.fvg import detect_fvg


TOOL_SCHEMA = {
    "name": "check_absorption_at_poi",
    "description": (
        "Check whether the current bar shows institutional absorption "
        "(high volume + small range + close near high/low) at an active POI "
        "(unmitigated Order Block or untouched FVG). "
        "Absorption at POI = hidden buying/selling before a reversal. "
        "Use after price reaches an OB or FVG zone to confirm institutional "
        "interest before entering. Does NOT require delta data."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol":            {"type": "string"},
            "timeframe":         {"type": "string", "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"]},
            "bars":              {"type": "integer", "default": 300},
            "min_volume_pct":    {
                "type": "number", "default": 70.0,
                "description": (
                    "Last bar volume must exceed avg_volume * (this/100) "
                    "to qualify as high-volume"
                ),
            },
            "max_range_atr":     {
                "type": "number", "default": 0.5,
                "description": "Last bar range must be < ATR(14) * this to qualify as small-range",
            },
            "poi_tolerance_atr": {
                "type": "number", "default": 0.3,
                "description": (
                    "How far (in ATR) current price can be from POI edge "
                    "and still count as 'at POI'"
                ),
            },
        },
        "required": ["symbol", "timeframe"],
    },
}

_EMPTY_ABSORPTION = {
    "absorption_detected": False,
    "vol_ratio": 0.0,
    "range_atr_ratio": 0.0,
    "close_position": 0.0,
}


def check_absorption_at_poi(
    df: pd.DataFrame,
    min_volume_pct: float = 70.0,
    max_range_atr: float = 0.5,
    poi_tolerance_atr: float = 0.3,
) -> dict:
    # ------------------------------------------------------------------
    # Guard
    # ------------------------------------------------------------------
    if len(df) < 20:
        return {
            "absorption_detected": False,
            "poi_hit": False,
            "status": "insufficient_data",
            "poi_type": "none",
            "reversal_direction": "none",
            "poi_zone": None,
            "ob_detail": None,
            "fvg_detail": None,
            "absorption_detail": _EMPTY_ABSORPTION,
        }

    # ------------------------------------------------------------------
    # Absorption check (early exit keeps the no-absorption path cheap)
    # ------------------------------------------------------------------
    absorption = check_cd_absorption(df, min_volume_pct, max_range_atr)
    if not absorption["absorption_detected"]:
        return {
            "absorption_detected": False,
            "poi_hit": False,
            "poi_type": "none",
            "reversal_direction": "none",
            "poi_zone": None,
            "ob_detail": None,
            "fvg_detail": None,
            "absorption_detail": absorption,
        }

    # ------------------------------------------------------------------
    # ATR (true range) + tolerance
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
        atr = 1e-10

    tolerance = poi_tolerance_atr * atr
    current_price = float(df["close"].iloc[-1])

    # ------------------------------------------------------------------
    # OB check — unmitigated only; fields are "high"/"low"
    # ------------------------------------------------------------------
    ob_result = detect_order_block(df)
    matched_ob = None
    for ob in ob_result.get("obs", []):
        if ob["is_mitigated"]:
            continue
        if (ob["low"] - tolerance) <= current_price <= (ob["high"] + tolerance):
            matched_ob = ob
            break

    # ------------------------------------------------------------------
    # FVG check — untouched or IOFED only; fields are "upper"/"lower"
    # ------------------------------------------------------------------
    fvg_result = detect_fvg(df)
    matched_fvg = None
    for fvg in fvg_result.get("fvgs", []):
        if fvg["fill_state"] not in ("untouched", "IOFED"):
            continue
        if (fvg["lower"] - tolerance) <= current_price <= (fvg["upper"] + tolerance):
            matched_fvg = fvg
            break

    # ------------------------------------------------------------------
    # Resolve POI type, reversal direction, and zone
    # ------------------------------------------------------------------
    poi_hit = matched_ob is not None or matched_fvg is not None

    if matched_ob is not None and matched_fvg is not None:
        poi_type = "ob+fvg"
        reversal_direction = matched_ob["type"]
        poi_zone = {
            "low": min(float(matched_ob["low"]), float(matched_fvg["lower"])),
            "high": max(float(matched_ob["high"]), float(matched_fvg["upper"])),
        }
    elif matched_ob is not None:
        poi_type = "ob"
        reversal_direction = matched_ob["type"]
        poi_zone = {"low": float(matched_ob["low"]), "high": float(matched_ob["high"])}
    elif matched_fvg is not None:
        poi_type = "fvg"
        reversal_direction = matched_fvg["type"]
        poi_zone = {"low": float(matched_fvg["lower"]), "high": float(matched_fvg["upper"])}
    else:
        poi_type = "none"
        reversal_direction = "none"
        poi_zone = None

    return {
        "absorption_detected": True,
        "poi_hit": poi_hit,
        "poi_type": poi_type,
        "reversal_direction": reversal_direction,
        "poi_zone": poi_zone,
        "ob_detail": matched_ob,
        "fvg_detail": matched_fvg,
        "absorption_detail": absorption,
    }
