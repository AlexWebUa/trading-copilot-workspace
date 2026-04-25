"""
Journal persistence: append-only JSONL, in-place record updates.
"""

from __future__ import annotations

import json
from pathlib import Path

from copilot.journal.record import TradeRecord

_DEFAULT_PATH = Path.home() / ".trading-copilot" / "journal" / "journal.jsonl"


def default_journal_path() -> Path:
    return _DEFAULT_PATH


def append_record(record: TradeRecord, path: Path | None = None) -> Path:
    p = path or _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
    return p


def update_record(record_id: str, updates: dict, path: Path | None = None) -> bool:
    """Rewrite journal file with one record patched. Returns True if found."""
    p = path or _DEFAULT_PATH
    if not p.exists():
        return False

    lines = p.read_text(encoding="utf-8").splitlines()
    found = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            d = json.loads(stripped)
        except json.JSONDecodeError:
            new_lines.append(stripped)
            continue
        if d.get("id") == record_id:
            d.update(updates)
            found = True
        new_lines.append(json.dumps(d, ensure_ascii=False))

    if found:
        p.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return found
