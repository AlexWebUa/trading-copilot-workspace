"""Tests for generate_pine_script — the significant-detectors overlay tool."""

import numpy as np
import pandas as pd
import pytest

from copilot.detectors.fvg import detect_fvg
from copilot.detectors.liquidity import detect_liquidity
from copilot.detectors.pine_script import TOOL_SCHEMA, generate_pine_script
from copilot.pine.overlay import OVERLAY_LAYERS, layer_toggle


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
    for p in np.linspace(100, 110, 10):
        rows.append({"open": p - 0.3, "high": p + 0.5, "low": p - 0.8, "close": p, "volume": 1000.0})
    for p in np.linspace(110, 106, 5):
        rows.append({"open": p + 0.3, "high": p + 0.6, "low": p - 0.5, "close": p, "volume": 800.0})
    for p in np.linspace(106, 122, 15):
        rows.append({"open": p - 0.3, "high": p + 0.5, "low": p - 0.8, "close": p, "volume": 1200.0})
    rows.append({"open": 120.0, "high": 122.0, "low": 119.0, "close": 121.0, "volume": 800.0})
    rows.append({"open": 121.0, "high": 128.0, "low": 120.5, "close": 127.5, "volume": 2500.0})
    rows.append({"open": 127.0, "high": 129.0, "low": 124.0, "close": 128.0, "volume": 900.0})
    for p in np.linspace(128, 125, 10):
        rows.append({"open": p + 0.2, "high": p + 0.6, "low": p - 0.4, "close": p, "volume": 700.0})
    return _make_df(rows)


class TestLayerSelection:
    """Only the requested detectors get charted — that is the whole point."""

    def test_only_requested_layer_is_drawn(self):
        df = _make_rich_df()
        result = generate_pine_script(df, "BTCUSDT", "1h", detectors=["detect_fvg"])

        assert result["layers"] == ["detect_fvg"]
        assert list(result["layer_counts"]) == ["detect_fvg"]
        script = result["pine_script"]
        assert layer_toggle("detect_fvg") in script
        for other in OVERLAY_LAYERS:
            if other != "detect_fvg":
                assert layer_toggle(other) not in script

    def test_two_layers_both_present_and_ordered(self):
        df = _make_rich_df()
        result = generate_pine_script(
            df, "BTCUSDT", "1h", detectors=["detect_fvg", "detect_liquidity"]
        )
        # OVERLAY_LAYERS order wins over argument order: liquidity draws first
        # so FVG boxes land on top of the pool lines.
        assert result["layers"] == ["detect_liquidity", "detect_fvg"]
        script = result["pine_script"]
        assert script.index("(detect_liquidity)") < script.index("(detect_fvg)")

    def test_duplicate_names_collapse(self):
        df = _make_rich_df()
        result = generate_pine_script(
            df, "BTCUSDT", "1h", detectors=["detect_fvg", "detect_fvg"]
        )
        assert result["layers"] == ["detect_fvg"]
        assert result["pine_script"].count("if barstate.islast and") == 1

    def test_omitted_detectors_chart_every_layer(self):
        df = _make_rich_df()
        result = generate_pine_script(df, "BTCUSDT", "1h")
        assert result["layers"] == list(OVERLAY_LAYERS)


class TestFailSoft:
    def test_unknown_detector_returns_error_not_raise(self):
        df = _make_rich_df()
        result = generate_pine_script(df, "BTCUSDT", "1h", detectors=["detect_unicorn"])
        assert result["status"] == "error"
        assert "detect_unicorn" in result["error"]
        assert result["supported_layers"] == list(OVERLAY_LAYERS)
        assert "pine_script" not in result

    def test_quarantined_detector_is_rejected(self):
        """A detector hidden from the LLM must not be chartable either."""
        df = _make_rich_df()
        result = generate_pine_script(df, "BTCUSDT", "1h", detectors=["detect_compression"])
        assert result["status"] == "error"

    def test_empty_selection_returns_error(self):
        df = _make_rich_df()
        result = generate_pine_script(df, "BTCUSDT", "1h", detectors=[])
        assert result["status"] == "error"

    def test_flat_market_still_produces_a_script(self, flat_df):
        result = generate_pine_script(flat_df, "BTCUSDT", "1h", detectors=["detect_fvg"])
        assert result["zone_count"] == 0
        # The "nothing found" label keeps the indicator loadable on the chart.
        assert "No FVGs detected" in result["pine_script"]


class TestScriptShape:
    def test_header_names_symbol_and_timeframe(self):
        df = _make_rich_df()
        script = generate_pine_script(df, "ETHUSDT", "4h", detectors=["detect_fvg"])["pine_script"]
        assert '//@version=5' in script
        assert 'indicator("Co-Pilot: ETHUSDT 4h"' in script

    def test_anchor_declared_once_at_global_scope(self):
        """Layer blocks each open their own `if`, so anchor cannot live inside one."""
        df = _make_rich_df()
        script = generate_pine_script(
            df, "BTCUSDT", "1h", detectors=["detect_fvg", "detect_liquidity"]
        )["pine_script"]
        anchor_lines = [ln for ln in script.splitlines() if ln.startswith("anchor =")]
        assert anchor_lines == ["anchor = bar_index - (drop_forming ? 1 : 0)"]
        assert "    anchor = " not in script

    def test_every_layer_is_guarded_by_its_toggle(self):
        df = _make_rich_df()
        result = generate_pine_script(
            df, "BTCUSDT", "1h", detectors=["detect_fvg", "detect_liquidity"]
        )
        for detector in result["layers"]:
            assert f"if barstate.islast and {layer_toggle(detector)}" in result["pine_script"]

    def test_future_bars_extends_boxes(self):
        df = _make_rich_df()
        script = generate_pine_script(
            df, "BTCUSDT", "1h", detectors=["detect_fvg"], future_bars=99
        )["pine_script"]
        assert "anchor+99" in script
        assert "anchor+50" not in script

    def test_zone_count_matches_detector_output(self):
        """The chart draws what the detector found — no more, no less."""
        df = _make_rich_df()
        expected = detect_fvg(df)["count_active"]
        result = generate_pine_script(df, "BTCUSDT", "1h", detectors=["detect_fvg"])
        assert result["layer_counts"]["detect_fvg"] == expected
        assert result["pine_script"].count("box.new(") == expected

    def test_liquidity_pool_prices_reach_the_script(self, liquidity_sweep_df):
        result = detect_liquidity(liquidity_sweep_df)
        pools = result.get("buyside_liquidity", []) + result.get("sellside_liquidity", [])
        script = generate_pine_script(
            liquidity_sweep_df, "BTCUSDT", "1h", detectors=["detect_liquidity"]
        )["pine_script"]
        for pool in pools:
            assert str(pool["price"]) in script


class TestSchema:
    def test_schema_enum_matches_supported_layers(self):
        prop = TOOL_SCHEMA["input_schema"]["properties"]["detectors"]
        assert prop["items"]["enum"] == list(OVERLAY_LAYERS)

    def test_detectors_is_required(self):
        """Making it optional in code but required in the schema is deliberate:
        the model must state its selection, while direct callers may omit it."""
        assert "detectors" in TOOL_SCHEMA["input_schema"]["required"]
