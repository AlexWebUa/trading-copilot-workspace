"""
Core agentic loop: multi-turn tool-use with Claude.

Flow:
  1. Build system prompt (KB core + query notes + session context).
  2. Send user message.
  3. Claude calls detector tools → we dispatch → return results.
  4. Repeat until stop_reason != "tool_use" or MAX_TURNS reached.
  5. Extract final text block → save report → return.

Prompt caching: the stable core system block is marked ephemeral → ~70-90% cost
reduction on cache hits within the same session.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

from copilot.detectors.sessions import current_killzone
from copilot.kb.selector import KBSelector
from copilot.llm.client import AnthropicClient, LLMClient
from copilot.llm.prompts import build_system_prompt
from copilot.llm.report import save_report
from copilot.llm.state import build_context_block, load_state, save_state
from copilot.llm.tools import ToolRegistry
from copilot.llm.trace import write_trace

MAX_TURNS = 12
DEFAULT_MODEL = "claude-opus-5"


class AgentLoopBudgetExceeded(RuntimeError):
    pass


class TradingAgent:
    def __init__(
        self,
        symbol: str,
        model: str | None = None,
        tool_registry: ToolRegistry | None = None,
        kb_selector: KBSelector | None = None,
        llm_client: LLMClient | None = None,
    ):
        self.symbol = symbol.upper()
        self.model = model or os.getenv("COPILOT_MODEL", DEFAULT_MODEL)
        self._registry = tool_registry or ToolRegistry()
        self._kb = kb_selector or KBSelector()
        self._client = llm_client or AnthropicClient()
        self._messages: list[dict] = []

    def reset(self) -> None:
        """Clear conversation history (new analysis session)."""
        self._messages = []

    def analyze(self, user_query: str, verbose: bool = False) -> str:
        """
        Run one analysis turn. May execute multiple LLM↔tool rounds internally.
        Returns the final text output from Claude.
        """
        core_notes, query_notes = self._kb.select_for_query(user_query)
        session_ctx = current_killzone()

        # Inject pre-computed diff from last analysis (computed at end of last run)
        prev_state = load_state(self.symbol)
        prev_context: str | None = (prev_state or {}).get("context_block") or None

        system = build_system_prompt(
            core_notes, query_notes, self.symbol, session_ctx, prev_context
        )

        self._messages.append({"role": "user", "content": user_query})

        all_tool_results: dict[str, Any] = {}

        for turn in range(MAX_TURNS):
            if verbose:
                print(f"  [turn {turn + 1}] calling {self.model}...", file=sys.stderr)

            resp = self._client.complete(
                model=self.model,
                system=system,
                registry=self._registry,
                messages=self._messages,
                max_tokens=4096,
            )

            self._messages.append(resp.assistant_message)

            if not resp.wants_tools:
                # Final response. The assistant turn was already appended above
                # — do NOT append it a second time, or the conversation history
                # holds two adjacent assistant turns.
                final_text = resp.text

                # Anti-hallucination guard: every price-like number in the report
                # must appear in at least one tool result. Fail loudly — but do not
                # raise: the check is heuristic and a false positive must never
                # discard a real analysis.
                unverified = _verify_report_numbers(final_text, all_tool_results)
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

                # Persist report and analysis state
                saved = save_report(self.symbol, final_text)
                if all_tool_results:
                    save_state(self.symbol, all_tool_results)
                if verbose:
                    print(f"  [saved] {saved}", file=sys.stderr)
                return final_text

            # Dispatch all tool calls
            tool_results: list[tuple[str, str]] = []
            for call in resp.tool_calls:
                if verbose:
                    print(f"  [tool] {call.name}({json.dumps(call.input, ensure_ascii=False)[:120]})", file=sys.stderr)
                result = self._registry.dispatch(call.name, call.input)
                write_trace(self.symbol, call.name, call.input, result)
                all_tool_results[_result_key(call.name, call.input)] = result
                tool_results.append(
                    (call.id, json.dumps(result, default=str, ensure_ascii=False))
                )

            self._messages.append(self._client.tool_result_message(tool_results))

        raise AgentLoopBudgetExceeded(
            f"Analysis did not complete within {MAX_TURNS} turns."
        )

    def follow_up(self, message: str, verbose: bool = False) -> str:
        """Send a follow-up message in the same conversation context."""
        return self.analyze(message, verbose=verbose)

    @property
    def history(self) -> list[dict]:
        return list(self._messages)


def _result_key(name: str, tool_input: dict) -> str:
    """Key tool results by (name, symbol, timeframe).

    One analysis calls the same detector on several timeframes (D1/H4/H1/M15/M3).
    Keying by name alone made each call overwrite the previous one, so
    save_state's cross-run diff only ever saw the last timeframe. The symbol
    guards against the LLM probing a correlated symbol mid-analysis.
    """
    sym = tool_input.get("symbol")
    tf = tool_input.get("timeframe")
    if sym is None and tf is None:
        return name  # no-DataFrame tools (multi_tf alignment, killzone)
    return f"{name}@{sym or '?'}@{tf or '?'}"


# Integer or decimal token; an optional thousands 'k' suffix is handled by the caller.
# The comma-grouped alternative comes first so "64,938" is consumed whole — split
# into "64" and "938" it produced a pair of bogus unverified values on every
# report that used thousands separators.
_NUM_TOKEN = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(k|K)?")


def _collect_result_numbers(obj: Any, out: set[float]) -> None:
    """Recursively gather numeric *field* values from tool results.

    Strings are skipped on purpose — ISO timestamps would pollute the set with
    year/month/day digits and mask real hallucinations.
    """
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(round(float(obj), 2))
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_result_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_result_numbers(v, out)


def _verify_report_numbers(report_text: str, tool_results: dict[str, Any]) -> list[str]:
    """Return the price-like tokens in the report that match no tool-result number.

    Heuristic, tuned for false-positive avoidance: skips R-multiples / percentages /
    timeframe labels (a digit immediately followed by a letter other than k), dates
    (digit beside '-'), times (digit beside ':'), and sub-10 ratios/counts. A 'k'
    suffix expands to thousands. Matching allows ~0.15% (min 1.0) tolerance so a
    rounded restatement (66.8k vs an exact 66789.0) still verifies.
    """
    known: set[float] = set()
    for r in tool_results.values():
        _collect_result_numbers(r, known)

    unverified: list[str] = []
    seen: set[str] = set()
    for m in _NUM_TOKEN.finditer(report_text):
        raw = m.group(0)
        suffix = m.group(2)
        start, end = m.start(), m.end()
        before = report_text[start - 1] if start > 0 else ""
        after = report_text[end] if end < len(report_text) else ""

        if after.isalpha() and after not in ("k", "K"):
            continue  # 1.5R, 15m, 4h, 1d, "67bars"
        if after == ":" or before == ":":
            continue  # time component (09:00)
        if after == "-" or before == "-":
            continue  # date component (2026-06-19)

        value = float(m.group(1).replace(",", "")) * (1000 if suffix else 1)
        if value < 10:
            continue  # fib ratios, small counts

        tol = max(1.0, value * 0.0015)
        if raw not in seen and not any(abs(value - k) <= tol for k in known):
            seen.add(raw)
            unverified.append(raw)
    return unverified
