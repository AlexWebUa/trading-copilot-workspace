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
import sys
from typing import Any

import anthropic

from copilot.detectors.sessions import current_killzone
from copilot.kb.selector import KBSelector
from copilot.llm.prompts import build_system_prompt
from copilot.llm.report import save_report
from copilot.llm.tools import ToolRegistry

MAX_TURNS = 12
DEFAULT_MODEL = "claude-sonnet-4-6"


class AgentLoopBudgetExceeded(RuntimeError):
    pass


class TradingAgent:
    def __init__(
        self,
        symbol: str,
        model: str | None = None,
        tool_registry: ToolRegistry | None = None,
        kb_selector: KBSelector | None = None,
    ):
        self.symbol = symbol.upper()
        self.model = model or os.getenv("COPILOT_MODEL", DEFAULT_MODEL)
        self._registry = tool_registry or ToolRegistry()
        self._kb = kb_selector or KBSelector()
        self._client = anthropic.Anthropic()
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
        system = build_system_prompt(core_notes, query_notes, self.symbol, session_ctx)

        self._messages.append({"role": "user", "content": user_query})

        for turn in range(MAX_TURNS):
            if verbose:
                print(f"  [turn {turn + 1}] calling {self.model}...", file=sys.stderr)

            resp = self._client.messages.create(
                model=self.model,
                system=system,
                tools=self._registry.as_anthropic_tools(),
                messages=self._messages,
                max_tokens=4096,
            )

            self._messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                # Extract text from final response
                final_text = _extract_text(resp.content)
                self._messages.append({
                    "role": "assistant",
                    "content": final_text,
                })
                # Persist
                saved = save_report(self.symbol, final_text)
                if verbose:
                    print(f"  [saved] {saved}", file=sys.stderr)
                return final_text

            # Dispatch all tool calls
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    if verbose:
                        print(f"  [tool] {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]})", file=sys.stderr)
                    result = self._registry.dispatch(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str, ensure_ascii=False),
                    })

            self._messages.append({"role": "user", "content": tool_results})

        raise AgentLoopBudgetExceeded(
            f"Analysis did not complete within {MAX_TURNS} turns."
        )

    def follow_up(self, message: str, verbose: bool = False) -> str:
        """Send a follow-up message in the same conversation context."""
        return self.analyze(message, verbose=verbose)

    @property
    def history(self) -> list[dict]:
        return list(self._messages)


def _extract_text(content: list[Any]) -> str:
    parts = []
    for block in content:
        if hasattr(block, "text"):
            parts.append(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block["text"])
    return "\n".join(parts).strip()
