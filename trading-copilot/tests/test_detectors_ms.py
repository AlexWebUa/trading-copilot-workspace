"""Tests for copilot/detectors/market_structure.py"""

import numpy as np
import pandas as pd
import pytest
from copilot.detectors.market_structure import detect_market_structure


def _make_df(rows, freq="1h"):
    index = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, index=index)
    df.index.name = "ts"
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype("float64")
    return df[["open", "high", "low", "close", "volume"]]


def _cbos_bullish_df():
    """
    Bullish cBOS: pattern ["low","high","low","high"] where C < A (LL) and D > B (HH).
    L1=90 → H1=100 → L2=85 (LL) → H2=110 (HH)
    """
    rows = []
    for p in np.linspace(95, 90, 8):
        rows.append({"open": p + 0.2, "high": p + 1.0, "low": p - 1.0, "close": p, "volume": 500.0})
    for p in np.linspace(90, 100, 8):
        rows.append({"open": p - 0.2, "high": p + 1.0, "low": p - 1.0, "close": p, "volume": 500.0})
    for p in np.linspace(100, 85, 8):
        rows.append({"open": p + 0.2, "high": p + 1.0, "low": p - 1.0, "close": p, "volume": 500.0})
    for p in np.linspace(85, 110, 10):
        rows.append({"open": p - 0.2, "high": p + 1.0, "low": p - 1.0, "close": p, "volume": 500.0})
    return _make_df(rows)


def test_bullish_structure_detected(bullish_trend_df):
    result = detect_market_structure(bullish_trend_df, swing_lookback=3)
    assert result["state"] == "bullish"
    assert "last_swing_high" in result
    assert "last_swing_low" in result
    assert result["last_swing_high"]["price"] > result["last_swing_low"]["price"]


def test_bearish_structure_detected(bearish_trend_df):
    result = detect_market_structure(bearish_trend_df, swing_lookback=3)
    assert result["state"] == "bearish"


def test_cbos_state_still_directional():
    df = _cbos_bullish_df()
    result = detect_market_structure(df, swing_lookback=3)
    assert result.get("state") in ("bullish", "bearish"), (
        f"expected bullish/bearish after cBOS, got {result.get('state')}"
    )
    assert result.get("last_bos_type") == "cBOS"


def test_flat_market_returns_ranging(flat_df):
    result = detect_market_structure(flat_df, swing_lookback=3)
    assert result.get("state") in ("ranging", None) or "status" in result


def test_insufficient_data(tiny_df):
    result = detect_market_structure(tiny_df)
    assert "status" in result
    assert result["status"] == "insufficient_data"


def test_return_schema(bullish_trend_df):
    result = detect_market_structure(bullish_trend_df, swing_lookback=3)
    if "status" not in result:
        for key in ("state", "last_swing_high", "last_swing_low", "bars_in_state",
                    "current_price", "atr_14", "last_bos_type"):
            assert key in result, f"missing key: {key}"


def test_no_strength_field(bullish_trend_df):
    result = detect_market_structure(bullish_trend_df, swing_lookback=3)
    if result.get("last_swing_high"):
        assert "strength" not in result["last_swing_high"]
