"""
Tests for the agent loop (copilot/llm/agent.py).

Uses unittest.mock to patch the Anthropic client — no real API calls.
Verifies that the loop correctly dispatches tool calls and terminates.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from copilot.llm.agent import (
    TradingAgent,
    AgentLoopBudgetExceeded,
    _result_key,
    _verify_report_numbers,
)


def _make_text_response(text: str):
    """Simulate a final Claude response with no tool calls."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    return resp


def _make_tool_use_response(tool_name: str, tool_input: dict, tool_id: str = "tool_abc"):
    """Simulate a Claude response that calls a tool."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_id
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [block]
    return resp


@patch("copilot.llm.client.anthropic.Anthropic")
def test_single_turn_no_tools(MockAnthropic):
    """Agent should return text directly when Claude doesn't call tools."""
    client = MockAnthropic.return_value
    client.messages.create.return_value = _make_text_response("# Analysis — BTCUSDT")

    agent = TradingAgent("BTCUSDT")
    result = agent.analyze("analyze btc")

    assert "Analysis" in result
    assert client.messages.create.call_count == 1


@patch("copilot.llm.client.anthropic.Anthropic")
def test_tool_call_then_final_response(MockAnthropic):
    """Agent should dispatch one tool call then accept the final text response."""
    client = MockAnthropic.return_value
    client.messages.create.side_effect = [
        _make_tool_use_response("detect_fvg", {"symbol": "BTCUSDT", "timeframe": "1h"}),
        _make_text_response("# Analysis done"),
    ]

    # Mock the tool registry so no real data fetch happens
    mock_registry = MagicMock()
    mock_registry.as_anthropic_tools.return_value = []
    mock_registry.dispatch.return_value = {"fvgs": [], "count_active": 0}

    agent = TradingAgent("BTCUSDT", tool_registry=mock_registry)
    result = agent.analyze("analyze btc")

    assert "Analysis" in result
    assert mock_registry.dispatch.call_count == 1
    assert client.messages.create.call_count == 2


@patch("copilot.llm.client.anthropic.Anthropic")
def test_budget_exceeded_raises(MockAnthropic):
    """Agent should raise AgentLoopBudgetExceeded after MAX_TURNS tool calls."""
    client = MockAnthropic.return_value
    # Always return a tool-use response (never terminates)
    client.messages.create.return_value = _make_tool_use_response(
        "detect_fvg", {"symbol": "BTCUSDT", "timeframe": "1h"}
    )

    mock_registry = MagicMock()
    mock_registry.as_anthropic_tools.return_value = []
    mock_registry.dispatch.return_value = {"fvgs": [], "count_active": 0}

    agent = TradingAgent("BTCUSDT", tool_registry=mock_registry)

    with pytest.raises(AgentLoopBudgetExceeded):
        agent.analyze("analyze btc")


@patch("copilot.llm.client.anthropic.Anthropic")
def test_follow_up_appends_to_history(MockAnthropic):
    """follow_up should carry conversation context from previous turn."""
    client = MockAnthropic.return_value
    client.messages.create.return_value = _make_text_response("response")

    mock_registry = MagicMock()
    mock_registry.as_anthropic_tools.return_value = []

    agent = TradingAgent("BTCUSDT", tool_registry=mock_registry)
    agent.analyze("first query")
    agent.follow_up("zoom into 15m")

    # Two separate analyze calls → messages list grows
    assert len(agent.history) >= 2


# ---------------------------------------------------------------------------
# P1-3 — multi-TF result keying, no duplicate assistant turn, anti-hallucination
# ---------------------------------------------------------------------------

@patch("copilot.llm.agent.save_state")
@patch("copilot.llm.client.anthropic.Anthropic")
def test_multi_tf_results_not_overwritten(MockAnthropic, mock_save_state):
    """Same detector on two timeframes must produce two distinct result keys
    (keying by name alone used to drop all but the last TF)."""
    client = MockAnthropic.return_value
    client.messages.create.side_effect = [
        _make_tool_use_response("detect_market_structure", {"symbol": "BTCUSDT", "timeframe": "1h"}, "t1"),
        _make_tool_use_response("detect_market_structure", {"symbol": "BTCUSDT", "timeframe": "4h"}, "t2"),
        _make_text_response("# done"),
    ]
    mock_registry = MagicMock()
    mock_registry.as_anthropic_tools.return_value = []
    mock_registry.dispatch.side_effect = [{"state": "bullish"}, {"state": "bearish"}]

    agent = TradingAgent("BTCUSDT", tool_registry=mock_registry)
    agent.analyze("analyze")

    saved_results = mock_save_state.call_args[0][1]
    assert len(saved_results) == 2
    assert any(k.endswith("@1h") for k in saved_results)
    assert any(k.endswith("@4h") for k in saved_results)


@patch("copilot.llm.client.anthropic.Anthropic")
def test_no_duplicate_assistant_message(MockAnthropic):
    """The final assistant turn must appear once, not twice, in history."""
    client = MockAnthropic.return_value
    client.messages.create.side_effect = [
        _make_tool_use_response("detect_fvg", {"symbol": "BTCUSDT", "timeframe": "1h"}),
        _make_text_response("# Analysis done"),
    ]
    mock_registry = MagicMock()
    mock_registry.as_anthropic_tools.return_value = []
    mock_registry.dispatch.return_value = {"fvgs": [], "count_active": 0}

    agent = TradingAgent("BTCUSDT", tool_registry=mock_registry)
    agent.analyze("analyze btc")

    roles = [m["role"] for m in agent.history]
    assert roles == ["user", "assistant", "user", "assistant"]  # no assistant,assistant adjacency


def test_result_key_includes_timeframe():
    assert _result_key("detect_fvg", {"symbol": "BTCUSDT", "timeframe": "4h"}) == "detect_fvg@BTCUSDT@4h"
    # No-DataFrame tools keep the bare name
    assert _result_key("current_killzone", {}) == "current_killzone"


def test_verify_report_numbers_flags_hallucinated_price():
    results = {"detect_fvg@BTCUSDT@1h": {"fvgs": [{"upper": 67100.0, "lower": 66950.0}]}}
    report = "Entry 67.10k, TP 70.50k"  # 67100 is from a tool; 70500 is invented
    unverified = _verify_report_numbers(report, results)
    assert "70.50k" in unverified
    assert "67.10k" not in unverified


def test_verify_report_numbers_ignores_rr_dates_and_times():
    results = {"x": {"price": 66200.0}}
    report = "2026-06-19 09:00 Kyiv — 1.5R to TP, equilibrium 66.2k, fib 0.705"
    assert _verify_report_numbers(report, results) == []
