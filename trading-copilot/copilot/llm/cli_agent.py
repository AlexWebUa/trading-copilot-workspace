"""
Alternative LLM backend: drive the Claude Code CLI (`claude -p`) instead of the
Messages API, so tokens are billed against the subscription plan rather than
usage-based API credits.

Why this is an *agent*, not an LLMClient
----------------------------------------
`AnthropicClient` fits behind the `LLMClient` seam because the Messages API
hands unresolved `tool_use` blocks back to the caller and `agent.py` dispatches
them. `claude -p` runs its **own** agent loop and never surfaces an unresolved
tool call — so the detectors have to be reachable from *inside* that loop. The
only channel for that is MCP, and the project already ships one
(`copilot/mcp_server.py`) over the very same `ToolRegistry`. The seam therefore
moves up one level: this class replaces `TradingAgent`, not `AnthropicClient`.

Billing
-------
Claude Code uses subscription OAuth credentials only when `ANTHROPIC_API_KEY` is
absent from its environment. `.env` sets that key for the API backend, so it is
stripped from the subprocess env (`_subprocess_env`) — otherwise the CLI would
silently fall back to API billing, defeating the whole point. Never add
`--bare`: it forces API-key-only auth.

Parity with TradingAgent
------------------------
`--output-format stream-json` emits the entire transcript — assistant `tool_use`
blocks, user `tool_result` blocks, and a final `result` message — so tool
results are reconstructable and every post-processing step of the API backend
still runs: per-call traces, the anti-hallucination check, the report file and
the state snapshot whose diff feeds the next run.

What is lost, and why it is acceptable:
  * Explicit `cache_control` placement — the CLI manages its own prompt cache.
  * `MAX_TURNS` as a hard ceiling — bounded by a wall-clock timeout instead.
  * ~17k tokens of Claude Code's own tool schemas are prepended to every run
    even with `--system-prompt`; that overhead is the price of plan billing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from copilot.detectors.sessions import current_killzone
from copilot.kb.selector import KBSelector
from copilot.llm.agent import _result_key, _verify_report_numbers
from copilot.llm.prompts import build_system_prompt
from copilot.llm.report import save_report
from copilot.llm.state import load_state, save_state
from copilot.llm.trace import write_trace

MCP_SERVER_NAME = "trading-copilot"
TOOL_PREFIX = f"mcp__{MCP_SERVER_NAME}__"

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_TIMEOUT_S = 900

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Claude Code ships a full coding toolbelt; none of it belongs in a market
# analysis. ToolSearch is deliberately NOT denied — the CLI defers MCP tool
# schemas and loads them on demand through it, so denying it would leave the
# detectors unreachable.
_DENIED_TOOLS = [
    "Bash", "Edit", "Write", "Read", "NotebookEdit", "Glob", "Grep",
    "Task", "Skill", "Workflow", "WebFetch", "WebSearch",
]

# The KB prompt names detectors bare (`detect_fvg`); over MCP they arrive
# prefixed. Bridge the two without rewriting prompts.py, which the API backend
# shares.
_CLI_ADDENDUM = f"""

# Tool Access (this session)

Every detector tool named above is exposed through the `{MCP_SERVER_NAME}` MCP
server as `{TOOL_PREFIX}<tool>` — e.g. `detect_fvg` is
`{TOOL_PREFIX}detect_fvg`. Those are the only tools you may use: you have no
file, shell or web access, and there is nothing to read from disk.

In the "What I Checked" section, write tool names WITHOUT the `{TOOL_PREFIX}`
prefix.

Produce the final report as your last message. Do not ask clarifying questions —
if information is missing, follow the TOOL FAILURE PROTOCOL above.
"""


class ClaudeCLIError(RuntimeError):
    """The `claude` subprocess failed, timed out, or reported an error result."""


# ---------------------------------------------------------------------------
# Subprocess plumbing
# ---------------------------------------------------------------------------

def _subprocess_env() -> dict[str, str]:
    """Environment for `claude`, with API-key auth removed.

    Claude Code prefers ANTHROPIC_API_KEY over the subscription OAuth token
    whenever the variable is present — and `.env` sets it for the API backend.
    Leaving it in place would route this backend back onto usage-based billing
    without any visible symptom, so it is dropped here rather than trusted to be
    unset. ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL would redirect auth the
    same way.
    """
    env = dict(os.environ)
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        env.pop(var, None)
    return env


def _workspace_dir() -> Path:
    """Scratch cwd for the subprocess.

    Running `claude` from the project root would auto-load CLAUDE.md and the
    repo's `.claude/` settings — pages of guidance about *developing* this
    codebase, which is noise for a market analysis and costs tokens every run.
    An empty directory gives the CLI nothing to discover. The MCP server still
    starts in the project root (its own `cwd` field below).
    """
    path = Path(os.getenv("COPILOT_CLI_WORKSPACE",
                          str(Path.home() / ".trading-copilot" / "cli_workspace")))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _mcp_config() -> str:
    """`--mcp-config` payload, as a JSON string (the flag accepts files or JSON).

    Built from the running interpreter rather than read from
    claude_desktop_config.json: that file carries absolute paths for one
    machine, whereas sys.executable is by definition an interpreter that can
    import `copilot`.
    """
    server: dict = {
        "command": sys.executable,
        "args": ["-m", "copilot.mcp_server"],
        "cwd": str(_PROJECT_ROOT),
    }
    # The detectors run inside this server, two processes down (copilot →
    # claude → mcp_server). Env is the only channel to it, and passing it
    # explicitly does not depend on `claude` forwarding its own environment.
    market = os.getenv("COPILOT_MARKET")
    if market:
        server["env"] = {"COPILOT_MARKET": market}

    return json.dumps({"mcpServers": {MCP_SERVER_NAME: server}})


def stream_claude_cli(argv: list[str], timeout: int = DEFAULT_TIMEOUT_S) -> Iterator[str]:
    """Run `claude` and yield its stdout lines as they arrive.

    stderr is drained on a thread — the CLI writes progress and warnings there,
    and a full pipe buffer would deadlock the stdout reader.
    """
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_subprocess_env(),
            cwd=str(_workspace_dir()),
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except FileNotFoundError as exc:
        raise ClaudeCLIError(
            f"`{argv[0]}` not found. Install the Claude Code CLI "
            "(https://claude.com/claude-code) or set COPILOT_CLAUDE_BIN."
        ) from exc

    timed_out: list[bool] = []

    def _kill() -> None:
        timed_out.append(True)
        proc.kill()

    timer = threading.Timer(timeout, _kill)
    timer.start()

    stderr_out: list[str] = []
    drain = threading.Thread(
        target=lambda: stderr_out.append(proc.stderr.read() or ""), daemon=True
    )
    drain.start()

    try:
        assert proc.stdout is not None
        yield from proc.stdout
    finally:
        timer.cancel()
        if proc.stdout is not None:
            proc.stdout.close()
        code = proc.wait()
        drain.join(timeout=5)

    if timed_out:
        raise ClaudeCLIError(f"`claude` exceeded the {timeout}s timeout and was killed.")
    if code != 0:
        tail = "".join(stderr_out).strip()[-1000:]
        raise ClaudeCLIError(f"`claude` exited with code {code}: {tail or '(no stderr)'}")


# ---------------------------------------------------------------------------
# stream-json decoding
# ---------------------------------------------------------------------------

def _content_blocks(event: dict) -> list[dict]:
    content = (event.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


def _decode_tool_result(content: Any) -> Any:
    """Turn an MCP tool_result payload back into the detector's result dict.

    `mcp_server.call_tool` returns one TextContent holding `json.dumps(result)`,
    so the normal path is list-of-text-blocks → JSON. Permission denials and
    transport errors arrive as a bare string instead; those are surfaced as an
    error dict so `_verify_report_numbers` still sees an entry (with no numbers
    in it) rather than nothing at all.
    """
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = [
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        if not parts:
            return {"error": f"Non-text tool result: {json.dumps(content, default=str)[:300]}"}
        text = "\n".join(parts)
    else:
        return {"error": f"Unrecognised tool result payload: {type(content).__name__}"}

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": text[:2000]}


class _StreamResult:
    __slots__ = ("text", "tool_results", "session_id")

    def __init__(self) -> None:
        self.text: str = ""
        self.tool_results: dict[str, Any] = {}
        self.session_id: str | None = None


def parse_stream(
    lines: Iterable[str],
    symbol: str,
    verbose: bool = False,
    on_tool: Callable[[str, dict, Any], None] | None = None,
) -> _StreamResult:
    """Fold a stream-json transcript into the pieces the post-processing needs.

    Only `mcp__trading-copilot__*` calls are recorded: the CLI's own housekeeping
    tools (notably ToolSearch, which loads the deferred MCP schemas) are not part
    of the analysis and must not pollute the trace or the anti-hallucination
    baseline.
    """
    out = _StreamResult()
    pending: dict[str, tuple[str, dict]] = {}   # tool_use_id -> (bare name, input)
    last_text = ""

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue  # the CLI occasionally prints non-JSON notices on stdout
        if not isinstance(event, dict):
            continue

        etype = event.get("type")

        if etype == "system" and event.get("subtype") == "init":
            out.session_id = event.get("session_id") or out.session_id
            servers = event.get("mcp_servers") or []
            broken = [s for s in servers if s.get("name") == MCP_SERVER_NAME
                      and s.get("status") != "connected"]
            if broken or not any(s.get("name") == MCP_SERVER_NAME for s in servers):
                raise ClaudeCLIError(
                    f"MCP server '{MCP_SERVER_NAME}' did not connect "
                    f"(status: {broken[0].get('status') if broken else 'absent'}). "
                    "The detectors are unreachable — aborting rather than letting "
                    "the model answer without data."
                )

        elif etype == "assistant":
            for block in _content_blocks(event):
                if block.get("type") == "tool_use":
                    name = block.get("name", "")
                    if not name.startswith(TOOL_PREFIX):
                        continue
                    bare = name[len(TOOL_PREFIX):]
                    tool_input = block.get("input") or {}
                    pending[block.get("id", "")] = (bare, tool_input)
                    if verbose:
                        print(
                            f"  [tool] {bare}("
                            f"{json.dumps(tool_input, ensure_ascii=False)[:120]})",
                            file=sys.stderr,
                        )
                elif block.get("type") == "text":
                    text = block.get("text", "")
                    if text.strip():
                        last_text = text

        elif etype == "user":
            for block in _content_blocks(event):
                if block.get("type") != "tool_result":
                    continue
                entry = pending.pop(block.get("tool_use_id", ""), None)
                if entry is None:
                    continue  # a non-detector tool, already filtered above
                name, tool_input = entry
                result = _decode_tool_result(block.get("content"))
                out.tool_results[_result_key(name, tool_input)] = result
                write_trace(symbol, name, tool_input, result)
                if on_tool is not None:
                    on_tool(name, tool_input, result)

        elif etype == "result":
            out.session_id = event.get("session_id") or out.session_id
            if event.get("is_error") or event.get("subtype") != "success":
                raise ClaudeCLIError(
                    f"claude returned {event.get('subtype')!r}: "
                    f"{str(event.get('result') or event.get('error'))[:500]}"
                )
            final = event.get("result")
            if isinstance(final, str) and final.strip():
                out.text = final

    if not out.text:
        # No `result` event (e.g. a truncated stream) — fall back to the last
        # assistant text block rather than losing a completed analysis.
        out.text = last_text
    return out


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ClaudeCLIAgent:
    """Drop-in replacement for `TradingAgent` backed by `claude -p`.

    Mirrors the public surface (`analyze`, `follow_up`, `reset`, `history`,
    `symbol`, `model`) so `cli.py` can swap backends without branching.
    """

    def __init__(
        self,
        symbol: str,
        model: str | None = None,
        kb_selector: KBSelector | None = None,
        timeout: int | None = None,
        runner: Callable[[list[str]], Iterable[str]] | None = None,
    ):
        self.symbol = symbol.upper()
        self.model = model or os.getenv("COPILOT_CLI_MODEL") or os.getenv(
            "COPILOT_MODEL", DEFAULT_MODEL
        )
        self._kb = kb_selector or KBSelector()
        self._bin = os.getenv("COPILOT_CLAUDE_BIN", "claude")
        self._timeout = timeout or int(os.getenv("COPILOT_CLI_TIMEOUT", DEFAULT_TIMEOUT_S))
        self._runner = runner
        self._session_id: str | None = None
        self._messages: list[dict] = []

    def reset(self) -> None:
        """Drop conversation history — the next analyze() starts a fresh CLI session."""
        self._messages = []
        self._session_id = None

    def analyze(self, user_query: str, verbose: bool = False) -> str:
        core_notes, query_notes = self._kb.select_for_query(user_query)
        prev_state = load_state(self.symbol)
        prev_context: str | None = (prev_state or {}).get("context_block") or None

        system = _flatten_system(
            build_system_prompt(
                core_notes, query_notes, self.symbol, current_killzone(), prev_context
            )
        ) + _CLI_ADDENDUM

        argv = self._build_argv(user_query, system)
        if verbose:
            resumed = f" (resuming {self._session_id})" if self._session_id else ""
            print(f"  [cli] {self._bin} -p ... --model {self.model}{resumed}", file=sys.stderr)

        self._messages.append({"role": "user", "content": user_query})

        lines = self._runner(argv) if self._runner else stream_claude_cli(argv, self._timeout)
        parsed = parse_stream(lines, self.symbol, verbose=verbose)

        self._session_id = parsed.session_id or self._session_id
        final_text = parsed.text
        if not final_text.strip():
            raise ClaudeCLIError("claude produced no final text output.")

        self._messages.append({"role": "assistant", "content": final_text})

        # Same guard as the API backend: every price-like number in the report
        # must appear in some tool result. Heuristic → warn loudly, never raise.
        unverified = _verify_report_numbers(final_text, parsed.tool_results)
        if unverified:
            print(
                f"  ⚠️  ANTI-HALLUCINATION: {len(unverified)} report value(s) "
                f"absent from every tool result: {', '.join(unverified[:12])}",
                file=sys.stderr,
            )
            write_trace(
                self.symbol, "_verify_report",
                {"unverified": unverified}, {"verified": False},
            )

        saved = save_report(self.symbol, final_text)
        if parsed.tool_results:
            save_state(self.symbol, parsed.tool_results)
        if verbose:
            print(f"  [saved] {saved}", file=sys.stderr)
        return final_text

    def follow_up(self, message: str, verbose: bool = False) -> str:
        """Continue the same CLI session (`--resume`), preserving its context."""
        return self.analyze(message, verbose=verbose)

    @property
    def history(self) -> list[dict]:
        return list(self._messages)

    def _build_argv(self, prompt: str, system: str) -> list[str]:
        argv = [
            self._bin,
            "-p", prompt,
            "--system-prompt", system,
            "--mcp-config", _mcp_config(),
            "--strict-mcp-config",
            # Prefix match: allows every detector tool without enumerating them,
            # so a new detector needs no change here.
            "--allowedTools", f"mcp__{MCP_SERVER_NAME}",
            "--disallowedTools", ",".join(_DENIED_TOOLS),
            "--model", self.model,
            "--output-format", "stream-json",
            "--verbose",
        ]
        if self._session_id:
            argv += ["--resume", self._session_id]
        return argv


def _flatten_system(blocks: list[dict]) -> str:
    """Collapse Anthropic system blocks into the plain string `--system-prompt` takes.

    The `cache_control` marker on the core block is dropped — Claude Code decides
    its own cache breakpoints and offers no flag to place them.
    """
    return "\n\n".join(
        b.get("text", "") for b in blocks if b.get("type") == "text"
    )
