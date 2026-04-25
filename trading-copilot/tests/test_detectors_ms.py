"""Tests for copilot/detectors/market_structure.py"""

from copilot.detectors.market_structure import detect_market_structure


def test_bullish_structure_detected(bullish_trend_df):
    result = detect_market_structure(bullish_trend_df, swing_lookback=3)
    assert result["state"] == "bullish"
    assert "last_swing_high" in result
    assert "last_swing_low" in result
    assert result["last_swing_high"]["price"] > result["last_swing_low"]["price"]


def test_bearish_structure_detected(bearish_trend_df):
    result = detect_market_structure(bearish_trend_df, swing_lookback=3)
    assert result["state"] == "bearish"


def test_flat_market_returns_ranging(flat_df):
    result = detect_market_structure(flat_df, swing_lookback=3)
    # Flat bars produce no fractals → ranging or insufficient
    assert result.get("state") in ("ranging", None) or "status" in result


def test_insufficient_data(tiny_df):
    result = detect_market_structure(tiny_df)
    assert "status" in result
    assert result["status"] == "insufficient_data"


def test_swing_strength_field(bullish_trend_df):
    result = detect_market_structure(bullish_trend_df, swing_lookback=3)
    if "last_swing_high" in result and result["last_swing_high"]:
        assert result["last_swing_high"]["strength"] in ("strong", "weak")


def test_return_schema(bullish_trend_df):
    result = detect_market_structure(bullish_trend_df, swing_lookback=3)
    if "status" not in result:
        assert "state" in result
        assert "bars_in_state" in result
