"""
Backend selection: Messages API (usage-based billing) vs Claude Code CLI
(subscription plan limits).

Both backends expose the same surface — `analyze`, `follow_up`, `reset`,
`history`, `symbol`, `model` — so callers never branch on which one is active.
Imports are deferred so choosing one backend doesn't drag in the other's
dependencies.
"""

from __future__ import annotations

import os
from typing import Any

API = "api"
CLI = "cli"
BACKENDS = (API, CLI)

DEFAULT_BACKEND = API


def resolve_backend(name: str | None = None) -> str:
    """Explicit argument > COPILOT_BACKEND > api.

    Defaults to `api` so an existing install keeps its current billing and
    behaviour until the user opts in.
    """
    value = (name or os.getenv("COPILOT_BACKEND") or DEFAULT_BACKEND).strip().lower()
    if value not in BACKENDS:
        raise ValueError(f"Unknown backend {value!r}. Expected one of: {', '.join(BACKENDS)}")
    return value


def build_agent(symbol: str, model: str, backend: str | None = None) -> Any:
    """Construct the agent for the selected backend."""
    chosen = resolve_backend(backend)
    if chosen == CLI:
        from copilot.llm.cli_agent import ClaudeCLIAgent
        return ClaudeCLIAgent(symbol=symbol, model=model)
    from copilot.llm.agent import TradingAgent
    return TradingAgent(symbol=symbol, model=model)
