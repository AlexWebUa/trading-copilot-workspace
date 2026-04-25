"""
Tests for the agent loop (copilot/llm/agent.py).

Uses unittest.mock to patch the Anthropic client — no real API calls.
Verifies that the loop correctly dispatches tool calls and terminates.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from copilot.llm.agent import TradingAgent, AgentLoopBudgetExceeded


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


@patch("copilot.llm.agent.anthropic.Anthropic")
def test_single_turn_no_tools(MockAnthropic):
    """Agent should return text directly when Claude doesn't call tools."""
    client = MockAnthropic.return_value
    client.messages.create.return_value = _make_text_response("# Analysis — BTCUSDT")

    agent = TradingAgent("BTCUSDT")
    result = agent.analyze("analyze btc")

    assert "Analysis" in result
    assert client.messages.create.call_count == 1


@patch("copilot.llm.agent.anthropic.Anthropic")
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


@patch("copilot.llm.agent.anthropic.Anthropic")
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


@patch("copilot.llm.agent.anthropic.Anthropic")
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
