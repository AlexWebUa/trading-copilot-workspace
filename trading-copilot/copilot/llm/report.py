"""
Report persistence: saves the final analysis to disk.

Reports are written to ~/.trading-copilot/reports/{symbol}_{timestamp}.md
and also appended to a session log.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path


def _reports_dir() -> Path:
    env = os.getenv("TRADING_COPILOT_REPORTS_DIR")
    d = Path(env).expanduser() if env else Path.home() / ".trading-copilot" / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_report(symbol: str, content: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{symbol.upper()}_{ts}.md"
    path = _reports_dir() / filename
    path.write_text(content, encoding="utf-8")
    return path


def list_recent_reports(n: int = 10) -> list[Path]:
    d = _reports_dir()
    reports = sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return reports[:n]


def read_report(path: Path) -> str:
    return path.read_text(encoding="utf-8")
