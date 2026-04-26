"""
Session trace logger — appends one JSONL record per tool call to
~/.trading-copilot/traces/{SYMBOL}_{YYYYMMDD}.jsonl
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_MAX_LIST_ITEMS = 3


def _trim_result(obj: Any, depth: int = 0) -> Any:
    """Recursively trim large lists so traces stay compact."""
    if isinstance(obj, dict):
        if depth > 3:
            return {k: "..." for k in list(obj)[:5]}
        return {k: _trim_result(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        trimmed = [_trim_result(x, depth + 1) for x in obj[:_MAX_LIST_ITEMS]]
        if len(obj) > _MAX_LIST_ITEMS:
            trimmed.append(f"... ({len(obj) - _MAX_LIST_ITEMS} more)")
        return trimmed
    return obj


def write_trace(
    symbol: str,
    tool_name: str,
    params: dict,
    result: Any,
    ts: datetime | None = None,
) -> None:
    ts = ts or datetime.now(timezone.utc)
    date_str = ts.strftime("%Y%m%d")
    path = Path.home() / ".trading-copilot" / "traces" / f"{symbol.upper()}_{date_str}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": tool_name,
        "params": params,
        "result": _trim_result(result),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
