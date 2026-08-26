"""
Tests for the Claude Code CLI backend (copilot/llm/cli_agent.py).

The subprocess is replaced by a `runner` that yields canned stream-json lines
(captured from a real `claude -p` run), so no CLI is spawned and no tokens are
spent. What matters here is that the transcript is folded back into exactly the
artefacts the API backend produces: keyed tool results, traces, the report, and
the state snapshot.
"""

import json
from unittest.mock import patch

import pytest

from copilot.llm.backend import build_agent, resolve_backend
from copilot.llm.cli_agent import (
    TOOL_PREFIX,
    ClaudeCLIAgent,
    ClaudeCLIError,
    _decode_tool_result,
    _flatten_system,
    parse_stream,
)


# ---------------------------------------------------------------------------
# stream-json fixtures
# ---------------------------------------------------------------------------

def _init(session_id="sess-1", status="connected"):
    return json.dumps({
        "type": "system", "subtype": "init", "session_id": session_id,
        "mcp_servers": [{"name": "trading-copilot", "status": status}],
    })


def _tool_use(name, tool_input, tool_id):
    return json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}
        ]},
    })


def _tool_result(tool_id, payload):
    """MCP results arrive as one TextContent holding json.dumps(result)."""
    return json.dumps({
        "type": "user",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_id,
             "content": [{"type": "text", "text": json.dumps(payload)}]}
        ]},
    })


def _assistant_text(text):
    return json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    })


def _result(text, session_id="sess-1", subtype="success", is_error=False):
    return json.dumps({
        "type": "result", "subtype": subtype, "is_error": is_error,
        "result": text, "session_id": session_id,
    })


def _stream(*lines):
    return list(lines)


# ---------------------------------------------------------------------------
# parse_stream
# ---------------------------------------------------------------------------

@patch("copilot.llm.cli_agent.write_trace")
def test_tool_results_keyed_by_symbol_and_timeframe(mock_trace):
    """Same detector on two TFs must survive as two entries, as in the API loop."""
    parsed = parse_stream(_stream(
        _init(),
        _tool_use(f"{TOOL_PREFIX}detect_market_structure",
                  {"symbol": "BTCUSDT", "timeframe": "1h"}, "t1"),
        _tool_result("t1", {"state": "bullish"}),
        _tool_use(f"{TOOL_PREFIX}detect_market_structure",
                  {"symbol": "BTCUSDT", "timeframe": "4h"}, "t2"),
        _tool_result("t2", {"state": "bearish"}),
        _result("# done"),
    ), symbol="BTCUSDT")

    assert parsed.tool_results == {
        "detect_market_structure@BTCUSDT@1h": {"state": "bullish"},
        "detect_market_structure@BTCUSDT@4h": {"state": "bearish"},
    }
    assert parsed.text == "# done"
    assert parsed.session_id == "sess-1"
    assert mock_trace.call_count == 2
    # Traces record the bare detector name, not the MCP-prefixed one
    assert mock_trace.call_args_list[0][0][1] == "detect_market_structure"


@patch("copilot.llm.cli_agent.write_trace")
def test_non_detector_tools_are_ignored(mock_trace):
    """ToolSearch loads the deferred MCP schemas; it is not part of the analysis
    and must not enter the trace or the anti-hallucination baseline."""
    parsed = parse_stream(_stream(
        _init(),
        _tool_use("ToolSearch", {"query": "select:detect_fvg"}, "t0"),
        _tool_result("t0", [{"type": "tool_reference", "tool_name": "x"}]),
        _tool_use(f"{TOOL_PREFIX}detect_fvg", {"symbol": "BTCUSDT", "timeframe": "1h"}, "t1"),
        _tool_result("t1", {"count_active": 2}),
        _result("# done"),
    ), symbol="BTCUSDT")

    assert list(parsed.tool_results) == ["detect_fvg@BTCUSDT@1h"]
    assert mock_trace.call_count == 1


def test_disconnected_mcp_server_aborts():
    """Without the MCP server the model has no data — better to fail than to let
    it answer from nothing."""
    with pytest.raises(ClaudeCLIError, match="did not connect"):
        parse_stream(_stream(_init(status="failed"), _result("# done")), symbol="BTCUSDT")


def test_error_result_raises():
    with pytest.raises(ClaudeCLIError, match="error_max_turns"):
        parse_stream(
            _stream(_init(), _result("ran out", subtype="error_max_turns", is_error=True)),
            symbol="BTCUSDT",
        )


def test_truncated_stream_falls_back_to_last_assistant_text():
    """A missing `result` event must not discard a completed analysis."""
    parsed = parse_stream(
        _stream(_init(), _assistant_text("# Analysis — BTCUSDT")),
        symbol="BTCUSDT",
    )
    assert parsed.text == "# Analysis — BTCUSDT"


def test_non_json_stdout_lines_are_skipped():
    parsed = parse_stream(
        _stream(_init(), "Ignoring 6 permissions.allow entries", "", _result("# done")),
        symbol="BTCUSDT",
    )
    assert parsed.text == "# done"


def test_decode_tool_result_variants():
    assert _decode_tool_result([{"type": "text", "text": '{"a": 1}'}]) == {"a": 1}
    # Permission denials come back as a bare string, not a content list
    denied = _decode_tool_result("permission not granted")
    assert denied == {"error": "permission not granted"}


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

@patch("copilot.llm.cli_agent.save_state")
@patch("copilot.llm.cli_agent.save_report", return_value="/tmp/report.md")
@patch("copilot.llm.cli_agent.write_trace")
@patch("copilot.llm.cli_agent.load_state", return_value=None)
def test_analyze_saves_report_and_state(mock_load, mock_trace, mock_report, mock_state):
    lines = _stream(
        _init(),
        _tool_use(f"{TOOL_PREFIX}detect_fvg", {"symbol": "BTCUSDT", "timeframe": "1h"}, "t1"),
        _tool_result("t1", {"fvgs": [{"upper": 67100.0}]}),
        _result("# Analysis — entry 67.10k"),
    )
    agent = ClaudeCLIAgent("BTCUSDT", runner=lambda argv: lines)

    out = agent.analyze("analyze btc")

    assert out == "# Analysis — entry 67.10k"
    mock_report.assert_called_once_with("BTCUSDT", out)
    assert mock_state.call_args[0][1] == {"detect_fvg@BTCUSDT@1h": {"fvgs": [{"upper": 67100.0}]}}
    assert [m["role"] for m in agent.history] == ["user", "assistant"]


@patch("copilot.llm.cli_agent.save_state")
@patch("copilot.llm.cli_agent.save_report", return_value="/tmp/report.md")
@patch("copilot.llm.cli_agent.write_trace")
@patch("copilot.llm.cli_agent.load_state", return_value=None)
def test_hallucinated_number_is_flagged(mock_load, mock_trace, mock_report, mock_state, capsys):
    lines = _stream(
        _init(),
        _tool_use(f"{TOOL_PREFIX}detect_fvg", {"symbol": "BTCUSDT", "timeframe": "1h"}, "t1"),
        _tool_result("t1", {"fvgs": [{"upper": 67100.0}]}),
        _result("Entry 67.10k, TP 70.50k"),  # 70500 came from nowhere
    )
    ClaudeCLIAgent("BTCUSDT", runner=lambda argv: lines).analyze("analyze")

    assert "ANTI-HALLUCINATION" in capsys.readouterr().err
    assert any(c[0][1] == "_verify_report" for c in mock_trace.call_args_list)


@patch("copilot.llm.cli_agent.save_state")
@patch("copilot.llm.cli_agent.save_report", return_value="/tmp/report.md")
@patch("copilot.llm.cli_agent.load_state", return_value=None)
def test_follow_up_resumes_the_cli_session(mock_load, mock_report, mock_state):
    """The CLI owns the conversation; continuity comes from --resume <session_id>."""
    captured: list[list[str]] = []

    def runner(argv):
        captured.append(argv)
        return _stream(_init(session_id="sess-42"), _result("ok", session_id="sess-42"))

    agent = ClaudeCLIAgent("BTCUSDT", runner=runner)
    agent.analyze("first")
    agent.follow_up("zoom into 15m")

    assert "--resume" not in captured[0]
    assert captured[1][captured[1].index("--resume") + 1] == "sess-42"

    agent.reset()
    agent.analyze("fresh")
    assert "--resume" not in captured[2]


@patch("copilot.llm.cli_agent.load_state", return_value=None)
def test_argv_carries_mcp_config_and_denies_coding_tools(mock_load):
    captured: list[list[str]] = []

    def runner(argv):
        captured.append(argv)
        return _stream(_init(), _result("ok"))

    with patch("copilot.llm.cli_agent.save_report", return_value="/tmp/r.md"):
        ClaudeCLIAgent("BTCUSDT", model="claude-sonnet-4-6", runner=runner).analyze("go")

    argv = captured[0]
    assert argv[:3] == ["claude", "-p", "go"]
    assert argv[argv.index("--model") + 1] == "claude-sonnet-4-6"
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--allowedTools") + 1] == "mcp__trading-copilot"

    mcp = json.loads(argv[argv.index("--mcp-config") + 1])
    assert mcp["mcpServers"]["trading-copilot"]["args"] == ["-m", "copilot.mcp_server"]

    denied = argv[argv.index("--disallowedTools") + 1].split(",")
    assert {"Bash", "Edit", "Write", "WebFetch"} <= set(denied)
    # ToolSearch loads the deferred MCP schemas — denying it would hide the detectors
    assert "ToolSearch" not in denied

    system = argv[argv.index("--system-prompt") + 1]
    assert "trading co-pilot" in system.lower()
    assert TOOL_PREFIX in system  # bare-name → prefixed-name bridge


def test_api_key_is_stripped_from_subprocess_env():
    """Claude Code prefers ANTHROPIC_API_KEY over subscription OAuth whenever it
    is set — and .env sets it. Leaving it in place would silently restore
    usage-based billing, which is the exact thing this backend exists to avoid."""
    from copilot.llm.cli_agent import _subprocess_env

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-secret", "PATH": "/usr/bin"}):
        env = _subprocess_env()

    assert "ANTHROPIC_API_KEY" not in env
    assert env["PATH"] == "/usr/bin"


def test_flatten_system_drops_cache_control_but_keeps_every_block():
    blocks = [
        {"type": "text", "text": "core", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "session ctx"},
    ]
    assert _flatten_system(blocks) == "core\n\nsession ctx"


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def test_backend_defaults_to_api_when_unset():
    with patch.dict("os.environ", {}, clear=True):
        assert resolve_backend() == "api"


def test_backend_reads_env_and_rejects_unknown():
    with patch.dict("os.environ", {"COPILOT_BACKEND": "cli"}):
        assert resolve_backend() == "cli"
        assert resolve_backend("api") == "api"  # explicit argument wins
    with pytest.raises(ValueError, match="Unknown backend"):
        resolve_backend("gpt")


def test_build_agent_returns_the_selected_implementation():
    from copilot.llm.agent import TradingAgent

    assert isinstance(build_agent("BTCUSDT", "claude-sonnet-4-6", "cli"), ClaudeCLIAgent)
    with patch("copilot.llm.client.anthropic.Anthropic"):
        assert isinstance(build_agent("BTCUSDT", "claude-sonnet-4-6", "api"), TradingAgent)
