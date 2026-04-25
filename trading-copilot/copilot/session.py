"""
REPL session state: symbol, model, last analysis, conversation history.
Persisted to ~/.trading-copilot/session.json between runs.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_TFS = ["1d", "4h", "1h", "15m", "3m"]

_SESSION_PATH = Path.home() / ".trading-copilot" / "session.json"


@dataclass
class Session:
    symbol: str = DEFAULT_SYMBOL
    model: str = DEFAULT_MODEL
    timeframes: list[str] = field(default_factory=lambda: list(DEFAULT_TFS))
    verbose: bool = False
    last_report: str = ""

    def save(self) -> None:
        _SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SESSION_PATH.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def load(cls) -> "Session":
        if not _SESSION_PATH.exists():
            return cls()
        try:
            data = json.loads(_SESSION_PATH.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except Exception:
            return cls()
