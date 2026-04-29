"""Tests for copilot/detectors/absorption_poi.py"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from copilot.detectors.absorption_poi import check_absorption_at_poi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(rows: list[dict]) -> pd.DataFrame:
    n = len(rows)
    ts = [datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(n)]
    df = pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))
    return df


def _normal_bar(close: float, h_off: float = 1.5, l_off: float = 1.5, vol: float = 1000.0) -> dict:
    return {
        "open":   close - 0.2,
        "high":   close + h_off,
        "low":    close - l_off,
        "close":  close,
        "volume": vol,
    }


def _narrow_bar(close: float, vol: float = 1000.0) -> dict:
    """Narrow-range bar (range=0.6) for pullback phases near POI zones."""
    return {
        "open":   close - 0.1,
        "high":   close + 0.3,
        "low":    close - 0.3,
        "close":  close,
        "volume": vol,
    }


# ---------------------------------------------------------------------------
# Test 1: Absorption at bullish Order Block
# ---------------------------------------------------------------------------

def test_absorption_detected_at_bullish_ob():
    """
    Real absorption bar (huge volume, tiny range, close near high) near a
    synthetic bullish OB at [99.0, 101.0].  detect_fvg is patched empty to
    prevent the pullback bars' descending gaps from masking the OB result.

    Expected: poi_hit=True, poi_type="ob", reversal_direction="bullish"
    """
    rows: list[dict] = []

    # 56 normal bars at ~110 — absorption bar is last
    for _ in range(56):
        rows.append(_normal_bar(110.0))

    # Absorption bar: close=100.3 (inside synthetic OB [99,101]), tiny range, huge volume
    rows.append({
        "open":   100.20,
        "high":   100.40,
        "low":    100.18,
        "close":  100.34,
        "volume": 5000.0,
    })

    df = _make_df(rows)

    fake_ob = {
        "type": "bullish",
        "high": 101.0,
        "low":  99.0,
        "formed_ts": "2026-01-01T00:00:00",
        "has_fvg_after": False,
        "is_mitigated": False,
        "distance_atr": 0.05,
        "age_bars": 20,
    }

    with patch("copilot.detectors.absorption_poi.detect_order_block") as mock_ob, \
         patch("copilot.detectors.absorption_poi.detect_fvg") as mock_fvg:
        mock_ob.return_value = {"obs": [fake_ob], "count": 1}
        mock_fvg.return_value = {"fvgs": [], "count_active": 0}

        result = check_absorption_at_poi(df)

    assert result["absorption_detected"] is True
    assert result["poi_hit"] is True
    assert result["poi_type"] == "ob"
    assert result["reversal_direction"] == "bullish"
    assert result["ob_detail"] is not None
    assert result["ob_detail"]["is_mitigated"] is False
    assert result["fvg_detail"] is None
    assert isinstance(result["poi_zone"], dict)
    assert result["poi_zone"]["low"] < result["poi_zone"]["high"]


# ---------------------------------------------------------------------------
# Test 2: Absorption at bullish FVG (no OB match)
# ---------------------------------------------------------------------------

def test_absorption_detected_at_fvg():
    """
    Real absorption bar with a synthetic bullish FVG at [102, 105].
    detect_order_block is patched empty to prevent OB interference.
    detect_fvg is patched with a specific bullish "IOFED" FVG.

    Expected: poi_hit=True, poi_type="fvg", reversal_direction="bullish"
    """
    rows: list[dict] = []

    # 56 normal bars at ~108 — gives check_cd_absorption enough history
    for _ in range(56):
        rows.append(_normal_bar(108.0, vol=600.0))

    # Absorption bar: close=104.12 (inside synthetic FVG [102,105])
    rows.append({
        "open":   104.05,
        "high":   104.15,
        "low":    104.05,
        "close":  104.12,
        "volume": 3000.0,   # 5× avg ≈ 600 → vol_ratio ≈ 5
    })

    df = _make_df(rows)

    fake_fvg = {
        "type": "bullish",
        "upper": 105.0,
        "lower": 102.0,
        "formed_ts": "2026-01-01T10:00:00",
        "fill_percentage": 31.7,
        "fill_state": "IOFED",
        "age_bars": 10,
        "width_atr_fraction": 1.0,
    }

    with patch("copilot.detectors.absorption_poi.detect_order_block") as mock_ob, \
         patch("copilot.detectors.absorption_poi.detect_fvg") as mock_fvg:
        mock_ob.return_value = {"obs": [], "count": 0}
        mock_fvg.return_value = {"fvgs": [fake_fvg], "count_active": 1}

        result = check_absorption_at_poi(df)

    assert result["absorption_detected"] is True
    assert result["poi_hit"] is True
    assert result["poi_type"] == "fvg"
    assert result["reversal_direction"] == "bullish"
    assert result["fvg_detail"] is not None
    assert result["fvg_detail"]["fill_state"] in ("untouched", "IOFED")
    assert result["ob_detail"] is None


# ---------------------------------------------------------------------------
# Test 3: Absorption at both OB and FVG (mocked sub-detectors)
# ---------------------------------------------------------------------------

def test_absorption_at_both_ob_and_fvg():
    """
    Patch detect_order_block and detect_fvg to return synthetic results
    with overlapping zones near the absorption bar price (~104).
    Tests the poi_type="ob+fvg" resolution logic directly.
    """
    rows: list[dict] = []
    # 25 normal bars (enough for guard + check_cd_absorption)
    for _ in range(25):
        rows.append(_normal_bar(110.0))
    # Absorption bar (last): huge vol, tiny range, close near high
    rows.append({
        "open":   104.00,
        "high":   104.10,
        "low":    103.90,
        "close":  104.06,
        "volume": 5000.0,
    })
    df = _make_df(rows)

    fake_ob = {
        "type": "bullish",
        "high": 105.0,
        "low":  103.0,
        "formed_ts": "2026-01-01T00:00:00",
        "has_fvg_after": False,
        "is_mitigated": False,
        "distance_atr": 0.1,
        "age_bars": 10,
    }
    fake_fvg = {
        "type": "bullish",
        "upper": 106.0,
        "lower": 103.5,
        "formed_ts": "2026-01-01T06:00:00",
        "fill_percentage": 10.0,
        "fill_state": "IOFED",
        "age_bars": 5,
        "width_atr_fraction": 0.5,
    }

    with patch("copilot.detectors.absorption_poi.detect_order_block") as mock_ob, \
         patch("copilot.detectors.absorption_poi.detect_fvg") as mock_fvg:
        mock_ob.return_value = {"obs": [fake_ob], "count": 1}
        mock_fvg.return_value = {"fvgs": [fake_fvg], "count_active": 1}

        result = check_absorption_at_poi(df)

    assert result["absorption_detected"] is True
    assert result["poi_hit"] is True
    assert result["poi_type"] == "ob+fvg"
    assert result["reversal_direction"] == "bullish"
    assert result["ob_detail"] is not None
    assert result["fvg_detail"] is not None
    # Combined zone should span both OB and FVG zones
    assert result["poi_zone"] is not None
    assert result["poi_zone"]["low"] <= min(fake_ob["low"], fake_fvg["lower"])
    assert result["poi_zone"]["high"] >= max(fake_ob["high"], fake_fvg["upper"])


# ---------------------------------------------------------------------------
# Test 4: Absorption present but no POI nearby
# ---------------------------------------------------------------------------

def test_absorption_no_poi():
    """
    Flat market (no OB impulse pattern, no FVG three-candle gap).
    Last bar triggers absorption, but no OB or FVG is near current price.

    Expected: absorption_detected=True, poi_hit=False, poi_type="none"
    """
    rows: list[dict] = []
    # 57 flat bars: no big impulse → detect_order_block finds nothing
    for _ in range(57):
        rows.append(_normal_bar(100.0, vol=1000.0))
    # Last bar: absorption (5× volume, tiny range, close near high)
    rows.append({
        "open":   100.0,
        "high":   100.1,
        "low":    99.96,
        "close":  100.08,
        "volume": 5000.0,
    })
    df = _make_df(rows)

    result = check_absorption_at_poi(df)

    assert result["absorption_detected"] is True
    assert result["poi_hit"] is False
    assert result["poi_type"] == "none"
    assert result["reversal_direction"] == "none"
    assert result["poi_zone"] is None
    assert result["ob_detail"] is None
    assert result["fvg_detail"] is None


# ---------------------------------------------------------------------------
# Test 5: No absorption, no POI
# ---------------------------------------------------------------------------

def test_no_absorption_no_poi():
    """
    Normal last bar (regular volume, normal range) and no POI patterns.
    All result fields must be present and have correct types.
    """
    rows: list[dict] = []
    for _ in range(40):
        rows.append(_normal_bar(100.0))
    df = _make_df(rows)

    result = check_absorption_at_poi(df)

    assert result["absorption_detected"] is False
    assert result["poi_hit"] is False
    # All mandatory keys present
    for key in ("poi_type", "reversal_direction", "poi_zone", "ob_detail",
                "fvg_detail", "absorption_detail"):
        assert key in result, f"Missing key: {key}"
    assert isinstance(result["absorption_detail"], dict)
    assert "vol_ratio" in result["absorption_detail"]


# ---------------------------------------------------------------------------
# Test 6: Insufficient data
# ---------------------------------------------------------------------------

def test_insufficient_data():
    rows = [_normal_bar(100.0) for _ in range(5)]
    df = _make_df(rows)

    result = check_absorption_at_poi(df)

    assert result["absorption_detected"] is False
    assert result["poi_hit"] is False
    assert result.get("status") == "insufficient_data"
    # All keys should still be present
    assert "poi_type" in result
    assert "reversal_direction" in result
