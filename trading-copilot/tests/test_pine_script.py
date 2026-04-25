"""Tests for generate_pine_script."""

import numpy as np
import pandas as pd
import pytest

from copilot.detectors.pine_script import generate_pine_script


def _make_df(rows: list[dict], freq: str = "1h") -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, index=index)
    df.index.name = "ts"
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype("float64")
    return df[["open", "high", "low", "close", "volume"]]


def _make_rich_df() -> pd.DataFrame:
    """Fixture with enough structure for multiple detectors to fire."""
    rows = []
    # Bullish zigzag with FVG and OB patterns
    for p in np.linspace(100, 110, 10):
        rows.append({"open": p - 0.3, "high": p + 0.5, "low": p - 0.8, "close": p, "volume": 1000.0})
    for p in np.linspace(110, 106, 5):
        rows.append({"open": p + 0.3, "high": p + 0.6, "low": p - 0.5, "close": p, "volume": 800.0})
    for p in np.linspace(106, 122, 15):
        rows.append({"open": p - 0.3, "high": p + 0.5, "low": p - 0.8, "close": p, "volume": 1200.0})
    # Explicit FVG candles
    rows.append({"open": 120.0, "high": 122.0, "low": 119.0, "close": 121.0, "volume": 800.0})
    rows.append({"open": 121.0, "high": 128.0, "low": 120.5, "close": 127.5, "volume": 2500.0})  # impulse
    rows.append({"open": 127.0, "high": 129.0, "low": 124.0, "close": 128.0, "volume": 900.0})
    # Continuation
    for p in np.linspace(128, 125, 10):
        rows.append({"open": p + 0.2, "high": p + 0.6, "low": p - 0.4, "close": p, "volume": 700.0})
    return _make_df(rows)


class TestGeneratePineScript:
    def test_returns_pine_script_string(self, bullish_trend_df):
        result = generate_pine_script(bullish_trend_df, symbol="BTCUSDT", timeframe="1h")
        assert "pine_script" in result
        assert isinstance(result["pine_script"], str)
        assert len(result["pine_script"]) > 100

    def test_pine_script_has_valid_header(self, bullish_trend_df):
        result = generate_pine_script(bullish_trend_df, symbol="ETHUSDT", timeframe="4h")
        script = result["pine_script"]
        assert "//@version=5" in script
        assert "indicator(" in script
        assert "ETHUSDT" in script
        assert "4h" in script

    def test_symbol_and_timeframe_in_header(self):
        df = _make_rich_df()
        result = generate_pine_script(df, symbol="SOLUSDT", timeframe="15m")
        script = result["pine_script"]
        assert "SOLUSDT" in script
        assert "15m" in script

    def test_summary_fields_present(self, bullish_trend_df):
        result = generate_pine_script(bullish_trend_df)
        assert "summary" in result
        summary = result["summary"]
        for key in ("fvgs", "obs", "ifvgs", "breakers", "bsl_pools", "ssl_pools", "bos"):
            assert key in summary, f"Missing key: {key}"

    def test_zone_count_is_non_negative(self, bullish_trend_df):
        result = generate_pine_script(bullish_trend_df)
        assert result["zone_count"] >= 0

    def test_rich_fixture_produces_zones(self):
        df = _make_rich_df()
        result = generate_pine_script(df, symbol="BTCUSDT", timeframe="1h")
        assert result["zone_count"] > 0

    def test_rich_fixture_script_contains_box_new(self):
        df = _make_rich_df()
        result = generate_pine_script(df, symbol="BTCUSDT", timeframe="1h")
        # At least some zones should be box.new calls
        script = result["pine_script"]
        assert "box.new(" in script or "line.new(" in script

    def test_future_bars_appears_in_script(self):
        df = _make_rich_df()
        result = generate_pine_script(df, future_bars=99)
        assert "bar_index+99" in result["pine_script"]

    def test_flat_market_no_crash(self, flat_df):
        result = generate_pine_script(flat_df)
        assert "pine_script" in result
        assert result["zone_count"] == 0

    def test_instructions_field_present(self, bullish_trend_df):
        result = generate_pine_script(bullish_trend_df)
        assert "instructions" in result
        assert "TradingView" in result["instructions"]

    def test_barstate_islast_present(self, bullish_trend_df):
        """All drawing code must be inside barstate.islast so it only runs once."""
        result = generate_pine_script(bullish_trend_df)
        assert "barstate.islast" in result["pine_script"]
