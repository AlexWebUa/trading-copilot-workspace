"""Tests for copilot/pine/ — layer registry, overlay assembly, artifact persistence."""

import json
from pathlib import Path

import pytest

from copilot.detectors.fvg import detect_fvg
from copilot.llm.tools import _ARTIFACT_TOOLS, _QUARANTINED_TOOLS, ToolRegistry
from copilot.pine.emitters import EMITTERS, EmitContext, emit
from copilot.pine.overlay import OVERLAY_LAYERS, build_overlay, layer_toggle
from copilot.pine.runners import RUNNERS
from copilot.pine.store import list_recent_pine, pine_dir, save_pine


class TestLayerRegistry:
    def test_overlay_layers_exclude_quarantined_detectors(self):
        """A detector the LLM cannot call must not be one it can chart.

        The two lists live in different modules; this pins them together so a
        future quarantine addition cannot silently leak onto the chart.
        """
        assert set(OVERLAY_LAYERS).isdisjoint(_QUARANTINED_TOOLS)

    def test_every_overlay_layer_has_an_emitter_and_a_runner(self):
        for detector in OVERLAY_LAYERS:
            assert detector in EMITTERS
            assert detector in RUNNERS

    def test_every_overlay_layer_has_a_distinct_toggle(self):
        toggles = [layer_toggle(d) for d in OVERLAY_LAYERS]
        assert len(set(toggles)) == len(toggles)

    def test_delta_and_info_layers_stay_out_of_the_overlay(self):
        """Explicitly deferred: delta needs columns the registry does not fetch
        for this tool, and the two info emitters draw tables, not price zones."""
        for detector in (
            "detect_cumulative_delta",
            "current_killzone",
            "check_multi_tf_alignment",
        ):
            assert detector in EMITTERS
            assert detector not in OVERLAY_LAYERS


class TestBuildOverlay:
    def _ctx(self, df):
        return EmitContext(df=df, bars=len(df), future_bars=50)

    def test_body_is_the_emitter_output_verbatim(self, fvg_bullish_df):
        """The overlay only wraps emitter output — it must not rewrite a line."""
        ctx = self._ctx(fvg_bullish_df)
        result = detect_fvg(fvg_bullish_df)
        body = emit("detect_fvg", result, ctx)

        script, _ = build_overlay(
            "BTCUSDT", "1h", ["detect_fvg"], {"detect_fvg": result}, ctx
        )
        for line in body:
            assert line in script.splitlines()

    def test_counts_come_from_the_detector(self, fvg_bullish_df):
        ctx = self._ctx(fvg_bullish_df)
        result = detect_fvg(fvg_bullish_df)
        _, counts = build_overlay(
            "BTCUSDT", "1h", ["detect_fvg"], {"detect_fvg": result}, ctx
        )
        assert counts == {"detect_fvg": result["count_active"]}

    def test_missing_result_degrades_to_a_nothing_label(self, fvg_bullish_df):
        """A layer whose detector errored still yields a loadable script."""
        ctx = self._ctx(fvg_bullish_df)
        script, counts = build_overlay("BTCUSDT", "1h", ["detect_fvg"], {}, ctx)
        assert counts == {"detect_fvg": 0}
        assert "No FVGs detected" in script

    def test_no_layers_still_emits_a_valid_header(self, fvg_bullish_df):
        script, counts = build_overlay("BTCUSDT", "1h", [], {}, self._ctx(fvg_bullish_df))
        assert counts == {}
        assert "//@version=5" in script
        assert "if barstate.islast" not in script

    def test_no_top_level_only_constructs_inside_layer_blocks(self, fvg_bullish_df):
        """plot/alertcondition/hline are illegal in an `if` — no emitter may use them."""
        ctx = self._ctx(fvg_bullish_df)
        script, _ = build_overlay(
            "BTCUSDT", "1h", ["detect_fvg"], {"detect_fvg": detect_fvg(fvg_bullish_df)}, ctx
        )
        indented = [ln for ln in script.splitlines() if ln.startswith("    ")]
        for line in indented:
            body = line.strip()
            assert not body.startswith(("plot(", "plotshape(", "alertcondition(", "hline("))


class TestArtifactStore:
    def test_save_pine_writes_under_isolated_home(self):
        path = save_pine("btcusdt", "1h", "// hello")
        assert path.read_text(encoding="utf-8") == "// hello"
        assert path.parent == pine_dir()
        assert path.name.startswith("BTCUSDT_1h_")
        assert path.suffix == ".pine"
        # isolated_home (conftest) must be in effect, or tests write into the
        # trader's real artifact directory.
        assert str(path).startswith(str(Path.home()))

    def test_env_override_redirects_output(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TRADING_COPILOT_PINE_DIR", str(tmp_path / "custom"))
        path = save_pine("ETHUSDT", "4h", "// x")
        assert path.parent == tmp_path / "custom"

    def test_list_recent_returns_newest_first(self):
        first = save_pine("BTCUSDT", "1h", "// one")
        second = save_pine("BTCUSDT", "4h", "// two")
        second.touch()
        assert list_recent_pine(2)[0] == second
        assert set(list_recent_pine(5)) == {first, second}


class _StubSource:
    """Registry data source that returns a fixture instead of hitting Binance."""

    def __init__(self, df):
        self._df = df
        self.calls = 0

    def get_ohlc(self, symbol, tf, bars, start_time=None, end_time=None):
        self.calls += 1
        return self._df


class TestRegistryIntegration:
    def test_pine_script_is_written_to_disk_not_returned(self, fvg_bullish_df):
        registry = ToolRegistry(data_source=_StubSource(fvg_bullish_df))
        result = registry.dispatch(
            "generate_pine_script",
            {"symbol": "BTCUSDT", "timeframe": "1h", "detectors": ["detect_fvg"]},
        )

        assert "pine_script" not in result, "raw Pine must not reach the model's context"
        saved = Path(result["pine_file"])
        assert saved.exists()
        assert "//@version=5" in saved.read_text(encoding="utf-8")
        assert result["layer_counts"]["detect_fvg"] == detect_fvg(fvg_bullish_df)["count_active"]

    def test_generate_pine_script_is_the_only_artifact_tool(self):
        assert _ARTIFACT_TOOLS == {"generate_pine_script"}

    def test_error_result_is_passed_through_unwritten(self, fvg_bullish_df):
        registry = ToolRegistry(data_source=_StubSource(fvg_bullish_df))
        result = registry.dispatch(
            "generate_pine_script",
            {"symbol": "BTCUSDT", "timeframe": "1h", "detectors": ["detect_compression"]},
        )
        assert result["status"] == "error"
        assert "pine_file" not in result
        assert not list(pine_dir().glob("*.pine"))

    def test_pine_file_path_survives_the_anti_hallucination_check(self, fvg_bullish_df):
        """The saved path carries digits (timestamp, timeframe). They must not be
        read as unverified price levels when the report cites the file."""
        from copilot.llm.agent import _verify_report_numbers

        registry = ToolRegistry(data_source=_StubSource(fvg_bullish_df))
        result = registry.dispatch(
            "generate_pine_script",
            {"symbol": "BTCUSDT", "timeframe": "1h", "detectors": ["detect_fvg"]},
        )
        report = f"## Chart\n- **File:** `{result['pine_file']}`\n- **Layers:** detect_fvg\n"
        assert _verify_report_numbers(report, {"generate_pine_script@BTCUSDT@1h": result}) == []


class TestArtifactCollisions:
    def test_same_second_writes_do_not_overwrite(self):
        """Two charts for one symbol/tf in the same second must both survive —
        the model is handed the first path before the second write happens."""
        first = save_pine("BTCUSDT", "1h", "// chart one")
        second = save_pine("BTCUSDT", "1h", "// chart two")

        assert first != second
        assert first.read_text(encoding="utf-8") == "// chart one"
        assert second.read_text(encoding="utf-8") == "// chart two"


class TestAlertConditions:
    """The pre-refactor generator emitted alertcondition() calls; keeping them
    is the difference between a static drawing and something that can page the
    trader when price reaches a pool."""

    def _ctx(self, df):
        return EmitContext(df=df, bars=len(df), future_bars=50)

    def test_liquidity_pools_produce_sweep_alerts(self, liquidity_sweep_df):
        from copilot.detectors.liquidity import detect_liquidity

        result = detect_liquidity(liquidity_sweep_df)
        script, _ = build_overlay(
            "BTCUSDT", "1h", ["detect_liquidity"], {"detect_liquidity": result},
            self._ctx(liquidity_sweep_df),
        )
        for pool in (result.get("buyside_liquidity") or [])[:5]:
            assert f'ta.crossover(high, {pool["price"]})' in script
        for pool in (result.get("sellside_liquidity") or [])[:5]:
            assert f'ta.crossunder(low, {pool["price"]})' in script

    def test_alerts_sit_at_top_level(self, liquidity_sweep_df):
        from copilot.detectors.liquidity import detect_liquidity

        script, _ = build_overlay(
            "BTCUSDT", "1h", ["detect_liquidity"],
            {"detect_liquidity": detect_liquidity(liquidity_sweep_df)},
            self._ctx(liquidity_sweep_df),
        )
        alert_lines = [ln for ln in script.splitlines() if "alertcondition(" in ln]
        assert alert_lines, "expected at least one alert for a swept-pool fixture"
        for line in alert_lines:
            assert not line.startswith(" "), "alertcondition inside an `if` is a Pine error"

    def test_layer_not_charted_contributes_no_alerts(self, liquidity_sweep_df):
        from copilot.detectors.liquidity import detect_liquidity

        script, _ = build_overlay(
            "BTCUSDT", "1h", ["detect_fvg"],
            {"detect_liquidity": detect_liquidity(liquidity_sweep_df)},
            self._ctx(liquidity_sweep_df),
        )
        assert "BSL Sweep" not in script
