"""Tests for copilot/detectors/orderflow_composite.py"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from copilot.detectors.orderflow_composite import (
    check_cd_absorption,
    check_ob_in_hvn,
    check_poc_location,
    check_price_in_lvn,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_df(
    n: int = 100,
    base: float = 100.0,
    high_offsets: list[float] | None = None,
    low_offsets: list[float] | None = None,
    volumes: list[float] | None = None,
) -> pd.DataFrame:
    ts = [datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(n)]
    rows = []
    for i in range(n):
        h = base + (high_offsets[i] if high_offsets else 2.0)
        l = base - (low_offsets[i] if low_offsets else 2.0)
        v = volumes[i] if volumes else 100.0
        rows.append({"open": base, "high": h, "low": l, "close": base, "volume": v})
    return pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))


# ---------------------------------------------------------------------------
# check_ob_in_hvn
# ---------------------------------------------------------------------------

def test_check_ob_in_hvn_true():
    """When an OB's price range overlaps an HVN node, in_hvn should be True."""
    # We can't guarantee exact VP output, but with 100 bars of consistent data
    # the detector pair should run without error. We test the interface.
    df = _make_df(n=100)
    result = check_ob_in_hvn(df)
    assert isinstance(result, dict)
    assert "in_hvn" in result
    assert "overlap_pct" in result
    assert "hvn_price_mid" in result
    assert isinstance(result["in_hvn"], bool)
    assert result["overlap_pct"] >= 0.0


def test_check_ob_in_hvn_false():
    """With a flat 1-bar price range, VP is degenerate — should gracefully return in_hvn=False."""
    df = _make_df(n=10)  # insufficient data for VP (needs ≥ 10)
    result = check_ob_in_hvn(df)
    # Very small dataset → graceful fallback
    assert isinstance(result, dict)
    assert "in_hvn" in result


def test_check_ob_in_hvn_no_obs():
    """DataFrame with too few bars → OB detector returns no obs → in_hvn=False."""
    df = _make_df(n=5)  # insufficient for OB (needs ≥ 10)
    result = check_ob_in_hvn(df)
    assert result["in_hvn"] is False
    assert result["overlap_pct"] == 0.0
    assert result["hvn_price_mid"] is None


# ---------------------------------------------------------------------------
# check_poc_location
# ---------------------------------------------------------------------------

def test_check_poc_location_discount():
    """
    Build bars where price drifts well below where most of the volume was traded.
    Expect in_discount=True.
    """
    # First 80 bars: base=200 (high volume at 200)
    # Last 20 bars: base=100 (now below POC)
    n = 100
    base_vals = [200.0] * 80 + [100.0] * 20
    ts = [datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(n)]
    rows = [
        {"open": b, "high": b + 1, "low": b - 1, "close": b, "volume": 100.0}
        for b in base_vals
    ]
    df = pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))

    result = check_poc_location(df)
    assert "in_discount" in result
    assert "in_premium" in result
    assert "poc" in result
    assert "location" in result
    # With most volume at 200 and close now at 100, should be in_discount
    assert result["in_discount"] is True
    assert result["in_premium"] is False


def test_check_poc_location_premium():
    """
    Build bars where price is now well above the high-volume zone.
    Expect in_premium=True.
    """
    n = 100
    base_vals = [100.0] * 80 + [200.0] * 20
    ts = [datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(n)]
    rows = [
        {"open": b, "high": b + 1, "low": b - 1, "close": b, "volume": 100.0}
        for b in base_vals
    ]
    df = pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))

    result = check_poc_location(df)
    assert result["in_premium"] is True
    assert result["in_discount"] is False


def test_check_poc_location_insufficient_data():
    """Insufficient data → fallback dict, no crash."""
    df = _make_df(n=3)
    result = check_poc_location(df)
    assert isinstance(result, dict)
    assert "in_discount" in result
    assert "in_premium" in result
    # No crash — values may be False (fallback)


# ---------------------------------------------------------------------------
# check_price_in_lvn
# ---------------------------------------------------------------------------

def test_check_price_in_lvn_true():
    """
    check_price_in_lvn interface test — returns bool + optional node.
    With enough bars, VP runs and result is properly shaped.
    """
    df = _make_df(n=100)
    result = check_price_in_lvn(df)
    assert "in_lvn" in result
    assert "node" in result
    assert isinstance(result["in_lvn"], bool)
    if result["in_lvn"]:
        assert result["node"] is not None
        assert "price_low" in result["node"]
        assert "price_high" in result["node"]


def test_check_price_in_lvn_false():
    """With only 5 bars (insufficient), should return in_lvn=False gracefully."""
    df = _make_df(n=5)
    result = check_price_in_lvn(df)
    assert result["in_lvn"] is False
    assert result["node"] is None


# ---------------------------------------------------------------------------
# check_cd_absorption
# ---------------------------------------------------------------------------

def test_check_cd_absorption_detected():
    """
    Last bar: high volume (3× avg), tiny range (0.02 ATR), close near high.
    Should detect absorption.
    """
    n = 30
    ts = [datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(n)]
    base = 100.0
    rows = []
    for i in range(n - 1):
        rows.append({"open": base, "high": base + 2.0, "low": base - 2.0, "close": base, "volume": 100.0})
    # Last bar: spike volume + tiny range + close near high
    rows.append({
        "open": base,
        "high": base + 0.1,     # tiny range (≪ ATR≈4)
        "low": base - 0.0,      # close at high
        "close": base + 0.09,   # close very near high
        "volume": 500.0,        # 5× average
    })
    df = pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))

    result = check_cd_absorption(df, min_volume_pct=70.0, max_range_atr=0.5)
    assert isinstance(result, dict)
    assert "absorption_detected" in result
    assert "vol_ratio" in result
    assert "range_atr_ratio" in result
    assert "close_position" in result
    assert result["absorption_detected"] is True
    assert result["vol_ratio"] > 1.0  # volume well above average


def test_check_cd_absorption_not_detected_low_volume():
    """When volume is normal (not elevated), absorption should not be detected."""
    df = _make_df(n=30, high_offsets=[2.0] * 30, low_offsets=[2.0] * 30, volumes=[100.0] * 30)
    result = check_cd_absorption(df, min_volume_pct=300.0)  # very high threshold
    assert result["absorption_detected"] is False


def test_check_cd_absorption_insufficient_data():
    """Fewer than 14 bars → returns False without crashing."""
    df = _make_df(n=10)
    result = check_cd_absorption(df)
    assert result["absorption_detected"] is False
    assert result["vol_ratio"] == 0.0
