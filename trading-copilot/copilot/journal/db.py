"""
SQLite database layer for the trade journal.

WAL mode + synchronous=NORMAL for safe concurrent writes without sacrificing
write throughput.  List fields (tp_prices, tools_confirmed, etc.) are stored
as JSON text columns.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from copilot.journal.record import TradeRecord

_DB_PATH = Path.home() / ".trading-copilot" / "journal" / "journal.db"
_JSONL_PATH = Path.home() / ".trading-copilot" / "journal" / "journal.jsonl"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS trades (
    id              TEXT PRIMARY KEY,
    record_type     TEXT NOT NULL DEFAULT 'trade',
    ts_created      TEXT NOT NULL,
    ts_entry        TEXT,
    ts_exit         TEXT,
    symbol          TEXT NOT NULL DEFAULT '',
    account_type    TEXT NOT NULL DEFAULT '',
    setup_name      TEXT NOT NULL DEFAULT '',
    direction       TEXT NOT NULL DEFAULT '',
    result          TEXT NOT NULL DEFAULT 'pending',
    day_of_week     INTEGER NOT NULL DEFAULT 0,
    entry_price     REAL,
    sl_price        REAL,
    exit_price      REAL,
    pnl_r           REAL,
    rr_planned      REAL,
    session         TEXT,
    killzone        TEXT,
    htf_bias        TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '',
    report_path     TEXT,
    tp_prices       TEXT NOT NULL DEFAULT '[]',
    tools_confirmed TEXT NOT NULL DEFAULT '[]',
    tools_pending   TEXT NOT NULL DEFAULT '[]',
    tags            TEXT NOT NULL DEFAULT '[]',
    partial_exits   TEXT NOT NULL DEFAULT '[]'
)
"""

_MIGRATIONS = [
    "ALTER TABLE trades ADD COLUMN partial_exits TEXT NOT NULL DEFAULT '[]'",
]

# List-type fields serialised as JSON text
_LIST_FIELDS = frozenset({"tp_prices", "tools_confirmed", "tools_pending", "tags", "partial_exits"})


def get_connection(path: Path | None = None) -> sqlite3.Connection:
    """Open (or create) the journal database and return an open connection."""
    p = path or _DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)

    # Delete legacy JSONL on first DB creation
    if not p.exists() and _JSONL_PATH.exists():
        _JSONL_PATH.unlink(missing_ok=True)

    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(_CREATE_TABLE)
    conn.commit()
    _apply_migrations(conn)
    return conn


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply schema migrations that add columns missing from older databases."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
    for stmt in _MIGRATIONS:
        # Extract the column name from "ALTER TABLE trades ADD COLUMN <name> ..."
        col = stmt.split("ADD COLUMN")[1].strip().split()[0]
        if col not in existing:
            try:
                conn.execute(stmt)
                conn.commit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Record ↔ SQLite row helpers
# ---------------------------------------------------------------------------

def _record_to_row(record: TradeRecord) -> dict:
    d = record.to_dict()
    for key in _LIST_FIELDS:
        d[key] = json.dumps(d.get(key) or [], ensure_ascii=False)
    return d


def _row_to_record(row: sqlite3.Row) -> TradeRecord:
    d = dict(row)
    for key in _LIST_FIELDS:
        raw = d.get(key)
        try:
            d[key] = json.loads(raw) if raw else []
        except (TypeError, json.JSONDecodeError):
            d[key] = []
    return TradeRecord.from_dict(d)
