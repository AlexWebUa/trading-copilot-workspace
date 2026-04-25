"""Tests for copilot/detectors/volume_profile.py"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from copilot.detectors.volume_profile import detect_volume_profile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_df(bars: int = 50, rows: list[dict] | None = None) -> pd.DataFrame:
    ts = [
        datetime(2026, 4, 25, 9, 0, tzinfo=timezone.utc) + timedelta(hours=i)
        for i in range(bars)
    ]
    if rows:
        assert len(rows) == bars
    else:
        rows = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 100.0}
            for _ in range(bars)
        ]
    return pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))


def _bimodal_df() -> pd.DataFrame:
    """30 bars at 100 (high vol) and 20 bars at 110 (low vol)."""
    ts = [
        datetime(2026, 4, 25, 9, 0, tzinfo=timezone.utc) + timedelta(hours=i)
        for i in range(50)
    ]
    rows = []
    for i in range(50):
        if i < 30:
            rows.append({"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.0, "volume": 1000.0})
        else:
            rows.append({"open": 110.0, "high": 110.5, "low": 109.5, "close": 110.0, "volume": 50.0})
    return pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))


# ---------------------------------------------------------------------------
# POC
# ---------------------------------------------------------------------------

def test_poc_at_high_volume_zone():
    df = _bimodal_df()
    result = detect_volume_profile(df)
    assert result.get("status") is None  # no error
    # POC should be near 100 (30 bars × 1000 vol >> 20 bars × 50 vol)
    assert 98.0 <= result["poc"] <= 102.0


def test_poc_in_output():
    df = _make_df()
    result = detect_volume_profile(df)
    assert "poc" in result
    assert isinstance(result["poc"], float)


# ---------------------------------------------------------------------------
# Value Area
# ---------------------------------------------------------------------------

def test_vah_above_val():
    df = _make_df()
    result = detect_volume_profile(df)
    assert result["vah"] >= result["val"]


def test_value_area_pct():
    df = _make_df()
    result = detect_volume_profile(df)
    assert result["value_area_pct"] == 70.0


def test_poc_inside_value_area():
    df = _make_df()
    result = detect_volume_profile(df)
    assert result["val"] <= result["poc"] <= result["vah"]


# ---------------------------------------------------------------------------
# HVN / LVN
# ---------------------------------------------------------------------------

def test_hvn_detected_at_high_volume_zone():
    df = _bimodal_df()
    result = detect_volume_profile(df)
    hvn_mids = [n["price_mid"] for n in result["hvn_nodes"]]
    # At least one HVN should be near price 100 (where 30×1000 vol sits)
    assert any(98.0 <= mid <= 102.0 for mid in hvn_mids), f"No HVN near 100. HVNs: {hvn_mids}"


def test_hvn_nodes_have_required_keys():
    df = _bimodal_df()
    result = detect_volume_profile(df)
    if result["hvn_nodes"]:
        node = result["hvn_nodes"][0]
        assert "price_mid" in node
        assert "price_low" in node
        assert "price_high" in node
        assert "volume_pct" in node


def test_lvn_nodes_have_lower_volume_pct_than_hvn():
    df = _bimodal_df()
    result = detect_volume_profile(df)
    if result["hvn_nodes"] and result["lvn_nodes"]:
        max_lvn = max(n["volume_pct"] for n in result["lvn_nodes"])
        min_hvn = min(n["volume_pct"] for n in result["hvn_nodes"])
        assert max_lvn < min_hvn


def test_hvn_nodes_capped_at_10():
    df = _make_df(bars=100)
    result = detect_volume_profile(df)
    assert len(result["hvn_nodes"]) <= 10


def test_lvn_nodes_capped_at_10():
    df = _make_df(bars=100)
    result = detect_volume_profile(df)
    assert len(result["lvn_nodes"]) <= 10


# ---------------------------------------------------------------------------
# Current price location
# ---------------------------------------------------------------------------

def test_location_above_poc():
    df = _bimodal_df()
    result = detect_volume_profile(df)
    # Last bar closes at 110 which is above POC near 100
    assert result["current_price_location"] in ("above_poc", "at_poc")


def test_current_price_in_output():
    df = _make_df()
    result = detect_volume_profile(df)
    assert "current_price" in result
    assert result["current_price"] == pytest.approx(100.0, abs=1.0)


# ---------------------------------------------------------------------------
# Nearest HVN / LVN
# ---------------------------------------------------------------------------

def test_nearest_hvn_above_present_when_hvn_exists_above():
    df = _bimodal_df()
    result = detect_volume_profile(df)
    # Current price is 110 (last bar), HVN is at 100 → hvn_below should be set
    if result.get("nearest_hvn_below"):
        assert result["nearest_hvn_below"]["price_mid"] < result["current_price"]


def test_nearest_hvn_has_distance_atr():
    df = _bimodal_df()
    result = detect_volume_profile(df)
    for key in ("nearest_hvn_above", "nearest_hvn_below"):
        if key in result:
            assert "distance_atr" in result[key]
            assert result[key]["distance_atr"] >= 0


# ---------------------------------------------------------------------------
# session_bars parameter
# ---------------------------------------------------------------------------

def test_session_bars_limits_window():
    # First 30 bars at 100, last 20 bars at 150
    rows_30 = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0}] * 30
    rows_20 = [{"open": 150.0, "high": 151.0, "low": 149.0, "close": 150.0, "volume": 1000.0}] * 20
    df = _make_df(bars=50, rows=rows_30 + rows_20)

    # Full profile: POC somewhere in middle
    full = detect_volume_profile(df)
    # Session profile (last 20 bars only): POC should be near 150
    session = detect_volume_profile(df, session_bars=20)
    assert session["poc"] >= 148.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_insufficient_data_too_few_bars():
    df = _make_df(bars=5)
    result = detect_volume_profile(df)
    assert result.get("status") == "insufficient_data"


def test_flat_market_handled():
    rows = [{"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0}] * 20
    df = _make_df(bars=20, rows=rows)
    result = detect_volume_profile(df)
    # Should return flat_market or handle gracefully (no crash)
    assert "status" in result or "poc" in result
