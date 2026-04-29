"""
Journal persistence: SQLite-backed record storage (WAL mode).
"""

from __future__ import annotations

from pathlib import Path

from copilot.journal.db import _DB_PATH, get_connection, _record_to_row
from copilot.journal.record import TradeRecord


def default_journal_path() -> Path:
    return _DB_PATH


def append_record(record: TradeRecord, path: Path | None = None) -> Path:
    conn = get_connection(path)
    row = _record_to_row(record)
    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" for _ in row)
    conn.execute(
        f"INSERT OR IGNORE INTO trades ({cols}) VALUES ({placeholders})",
        list(row.values()),
    )
    conn.commit()
    conn.close()
    return path or _DB_PATH


def update_record(record_id: str, updates: dict, path: Path | None = None) -> bool:
    """Update fields of an existing record. Returns True if found."""
    conn = get_connection(path)
    from copilot.journal.db import _LIST_FIELDS
    import json

    serialised = {}
    for k, v in updates.items():
        if k in _LIST_FIELDS:
            serialised[k] = json.dumps(v or [], ensure_ascii=False)
        else:
            serialised[k] = v

    if not serialised:
        conn.close()
        return False

    set_clause = ", ".join(f"{k} = ?" for k in serialised)
    cur = conn.execute(
        f"UPDATE trades SET {set_clause} WHERE id = ?",
        [*serialised.values(), record_id],
    )
    conn.commit()
    found = cur.rowcount > 0
    conn.close()
    return found
