"""
Tests for the P1-2 analysis-workflow revision.

Covers:
  - prompts.build_system_prompt: HTF-POI gate + conflict hierarchy present;
    phantom/quarantined tool names absent (regression guard).
  - state.build_context_block: HTF-POI lifecycle diffs (OB mitigation,
    breaker tested, sponsored-candle mitigated).

All fixtures are constructed in-test; no network, no API key.
"""

from copilot.llm.prompts import build_system_prompt
from copilot.llm.state import build_context_block

# Tools the prompt must NEVER instruct the LLM to call: phantom (no TOOL_SCHEMA,
# so unregistered) + quarantined (excluded from discovery in llm/tools.py).
_FORBIDDEN_TOOL_NAMES = [
    "check_ob_in_hvn",
    "check_poc_location",
    "check_price_in_lvn",
    "check_cd_absorption",
    "detect_compression",
    "check_absorption_at_poi",
    "check_cd_divergence_at_structure",
    "detect_rejection_block",
]


def _core_text(symbol: str = "BTCUSDT") -> str:
    """The cached core system block (role + KB + output format)."""
    blocks = build_system_prompt([], [], symbol)
    return blocks[0]["text"]


def test_prompt_contains_htf_poi_gate_and_hierarchy():
    text = _core_text()
    assert "HTF-POI HARD GATE" in text
    assert "No setup — no valid HTF POI" in text
    assert "CONFLICT HIERARCHY" in text
    # The hierarchy must rank orderflow as the lowest, context-only tier.
    assert "CONTEXT ONLY, lowest tier" in text
    # The new report section header.
    assert "## HTF POI" in text


def test_prompt_contains_position_management():
    text = _core_text()
    assert "POSITION MANAGEMENT" in text
    assert "80% at the First Trouble Area" in text
    assert "## Management" in text


def test_prompt_instructs_charting_only_significant_detectors():
    """The Pine overlay is worthless if the model charts everything it touched."""
    text = _core_text()
    # The instruction is wrapped across lines in the prompt source.
    flat = " ".join(text.split())
    assert "CHART OUTPUT" in text
    assert "generate_pine_script" in text
    # The judgement, stated plainly enough that the model cannot read it as
    # "chart every detector you called".
    assert "materially drove the verdict" in flat
    assert "checked and then discarded" in flat
    # And the report must have somewhere to put the resulting path.
    assert "## Chart" in text
    assert "pine_file" in text


def test_prompt_caps_chart_calls_at_two():
    flat = " ".join(_core_text().split())
    assert "Never more than two calls per analysis" in flat


def test_prompt_omits_phantom_and_quarantined_tools():
    """Regression guard: the prompt must not reference unregistered/quarantined tools."""
    text = _core_text()
    for name in _FORBIDDEN_TOOL_NAMES:
        assert name not in text, f"prompt references unavailable tool {name!r}"


def test_prompt_dropped_ob_in_hvn_upgrade_language():
    """The line-39 'upgrade POI quality' noise path must be gone."""
    text = _core_text()
    assert "upgrade POI quality" not in text
    assert "DOUBLE structural backing" not in text


def _ob(type_: str, high: float, low: float, mitigated: bool) -> dict:
    return {"type": type_, "high": high, "low": low, "is_mitigated": mitigated}


def test_context_block_reports_ob_mitigation():
    prev = {"results": {"detect_order_block@BTCUSDT@4h": {
        "obs": [_ob("bullish", 100.0, 95.0, False)]}}, "date": "20260621"}
    curr = {"detect_order_block@BTCUSDT@4h": {
        "obs": [_ob("bullish", 100.0, 95.0, True)]}}
    out = build_context_block(prev, curr)
    assert "HTF POI changes" in out
    assert "OB bullish_100.0_95.0: mitigated ✓" in out


def test_context_block_reports_breaker_tested_and_sc_mitigated():
    prev = {"results": {
        "detect_breaker_block@BTCUSDT@4h": {
            "breakers": [{"type": "bearish", "high": 110.0, "low": 108.0, "is_tested": False}]},
        "detect_sponsored_candle@BTCUSDT@4h": {
            "candles": [{"type": "bullish", "high": 90.0, "low": 88.0, "is_mitigated": False}]},
    }, "date": "20260621"}
    curr = {
        "detect_breaker_block@BTCUSDT@4h": {
            "breakers": [{"type": "bearish", "high": 110.0, "low": 108.0, "is_tested": True}]},
        "detect_sponsored_candle@BTCUSDT@4h": {
            "candles": [{"type": "bullish", "high": 90.0, "low": 88.0, "is_mitigated": True}]},
    }
    out = build_context_block(prev, curr)
    assert "Breaker bearish_110.0_108.0: tested ✓" in out
    assert "SC bullish_90.0_88.0: mitigated ✓" in out


def test_context_block_empty_when_no_poi_change():
    """No flag flip → no spurious HTF-POI lines (and empty string overall)."""
    prev = {"results": {"detect_order_block@BTCUSDT@4h": {
        "obs": [_ob("bullish", 100.0, 95.0, False)]}}, "date": "20260621"}
    curr = {"detect_order_block@BTCUSDT@4h": {
        "obs": [_ob("bullish", 100.0, 95.0, False)]}}
    out = build_context_block(prev, curr)
    assert out == ""
