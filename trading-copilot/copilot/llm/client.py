"""
LLM provider seam.

Isolates the provider-specific request/response shape (currently Anthropic's
Messages API) behind one small interface so the agent loop in `agent.py` deals
only in normalized `ToolCall` / `LLMResponse` objects — it never touches a
content block, a `stop_reason`, or a `tool_use_id` directly.

Adding another provider (e.g. an OpenAI-format client for OpenRouter) is a new
class here plus a translation of `build_system_prompt`'s blocks — not a rewrite
of the loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import anthropic

from copilot.llm.tools import ToolRegistry


@dataclass
class ToolCall:
    """A single tool invocation requested by the model, provider-normalized."""

    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    """One normalized model turn.

    `assistant_message` is the provider-shaped history entry the caller appends
    verbatim to the conversation — the loop never constructs it by hand.
    """

    text: str
    tool_calls: list[ToolCall]
    assistant_message: dict

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMClient(Protocol):
    """The contract the agent loop depends on. Implementations own all
    provider-specific request building and response parsing."""

    def complete(
        self,
        *,
        model: str,
        system: Any,
        registry: ToolRegistry,
        messages: list[dict],
        max_tokens: int,
    ) -> LLMResponse: ...

    def tool_result_message(self, results: list[tuple[str, str]]) -> dict:
        """Build the history entry that carries tool results back to the model.

        `results` is a list of `(tool_call_id, json_content)` pairs.
        """
        ...


class AnthropicClient:
    """Anthropic Messages API implementation of the seam.

    Reads `ANTHROPIC_API_KEY` from the environment (SDK default). The system
    prompt is passed through as-is: `build_system_prompt` already emits the
    Messages-API block list (with `cache_control`), which is Anthropic-shaped.
    """

    def __init__(self) -> None:
        self._client = anthropic.Anthropic()

    def complete(
        self,
        *,
        model: str,
        system: Any,
        registry: ToolRegistry,
        messages: list[dict],
        max_tokens: int,
    ) -> LLMResponse:
        resp = self._client.messages.create(
            model=model,
            system=system,
            tools=registry.as_anthropic_tools(),
            messages=messages,
            max_tokens=max_tokens,
        )
        tool_calls = [
            ToolCall(id=block.id, name=block.name, input=block.input)
            for block in resp.content
            if block.type == "tool_use"
        ]
        return LLMResponse(
            text=_extract_text(resp.content),
            tool_calls=tool_calls,
            # Re-append the SDK's own content blocks; the SDK round-trips them.
            assistant_message={"role": "assistant", "content": resp.content},
        )

    def tool_result_message(self, results: list[tuple[str, str]]) -> dict:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": call_id, "content": content}
                for call_id, content in results
            ],
        }


def _extract_text(content: list[Any]) -> str:
    """Join the text blocks of an assistant turn.

    Keyed on block *type* (`"text"`), not on the presence of a `.text`
    attribute: a `ToolUseBlock` has no text, and this is now called on every
    turn (tool-use turns included), not only the final one.
    """
    parts = []
    for block in content:
        btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if btype == "text":
            parts.append(block["text"] if isinstance(block, dict) else block.text)
    return "\n".join(parts).strip()
