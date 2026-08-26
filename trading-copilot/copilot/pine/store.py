"""
Pine artifact persistence — where generated indicators land on disk.

Mirrors `llm/report.py`: the directory is resolved on **every call** (not at
import) so the autouse `isolated_home` fixture in tests/conftest.py actually
isolates writes; resolving once at import would send fixture output into the
trader's real ~/.trading-copilot/pine/.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path


def pine_dir() -> Path:
    env = os.getenv("TRADING_COPILOT_PINE_DIR")
    d = Path(env).expanduser() if env else Path.home() / ".trading-copilot" / "pine"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_pine(symbol: str, tf: str, script: str) -> Path:
    """Write *script* and return its path.

    The name is timestamped to the second, but an analysis can chart two layer
    selections on the same symbol/timeframe within the same second — that
    collided, so the second chart silently overwrote the first and the path the
    model had already been handed pointed at the wrong content. Collisions now
    get a `-2`, `-3`, … suffix.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stem = f"{symbol.upper()}_{tf}_{ts}"
    directory = pine_dir()

    path = directory / f"{stem}.pine"
    seq = 2
    while path.exists():
        path = directory / f"{stem}-{seq}.pine"
        seq += 1

    path.write_text(script, encoding="utf-8")
    return path


def list_recent_pine(n: int = 10) -> list[Path]:
    files = sorted(pine_dir().glob("*.pine"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:n]
