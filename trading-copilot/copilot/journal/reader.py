"""
Journal queries: SQL-backed load, filter, and lookup.
"""

from __future__ import annotations

from pathlib import Path

from copilot.journal.db import _DB_PATH, get_connection, _row_to_record
from copilot.journal.record import TradeRecord


def load_all(path: Path | None = None) -> list[TradeRecord]:
    conn = get_connection(path)
    rows = conn.execute("SELECT * FROM trades ORDER BY ts_created ASC, rowid ASC").fetchall()
    conn.close()
    return [_row_to_record(r) for r in rows]


def filter_by(
    records: list[TradeRecord] | None = None,
    *,
    path: Path | None = None,
    record_type: str | None = None,
    symbol: str | None = None,
    account_type: str | None = None,
    setup_name: str | None = None,
    direction: str | None = None,
    result: str | None = None,
    session: str | None = None,
    htf_bias: str | None = None,
    tag: str | None = None,
    last: int | None = None,
) -> list[TradeRecord]:
    # If an in-memory list is already provided, filter it without hitting the DB
    if records is not None:
        return _filter_in_memory(records, record_type, symbol, account_type,
                                 setup_name, direction, result, session,
                                 htf_bias, tag, last)

    # Build SQL WHERE clause from provided kwargs
    conditions: list[str] = []
    params: list = []

    if record_type is not None:
        conditions.append("record_type = ?")
        params.append(record_type)
    if symbol is not None:
        conditions.append("upper(symbol) = upper(?)")
        params.append(symbol)
    if account_type is not None:
        conditions.append("account_type = ?")
        params.append(account_type)
    if setup_name is not None:
        conditions.append("setup_name = ?")
        params.append(setup_name)
    if direction is not None:
        conditions.append("direction = ?")
        params.append(direction)
    if result is not None:
        conditions.append("result = ?")
        params.append(result)
    if session is not None:
        conditions.append("session = ?")
        params.append(session)
    if htf_bias is not None:
        conditions.append("htf_bias = ?")
        params.append(htf_bias)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    if last is not None:
        # Get the last N rows by insertion order; rowid is stable tiebreaker
        sql = (
            f"SELECT * FROM ("
            f"  SELECT *, rowid AS _rid FROM trades {where} ORDER BY ts_created DESC, rowid DESC LIMIT {int(last)}"
            f") ORDER BY ts_created ASC, _rid ASC"
        )
    else:
        sql = f"SELECT * FROM trades {where} ORDER BY ts_created ASC, rowid ASC"

    conn = get_connection(path)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    result_list = [_row_to_record(r) for r in rows]

    # Tag filter is post-SQL (stored as JSON array)
    if tag is not None:
        result_list = [r for r in result_list if tag in r.tags]

    return result_list


def get_by_id(record_id: str, path: Path | None = None) -> TradeRecord | None:
    """Find a record by full ID or prefix."""
    conn = get_connection(path)
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (record_id,)).fetchone()
    if row is None:
        # Try prefix match
        row = conn.execute(
            "SELECT * FROM trades WHERE id LIKE ?", (record_id + "%",)
        ).fetchone()
    conn.close()
    return _row_to_record(row) if row else None


# ---------------------------------------------------------------------------
# Internal helper for in-memory filtering (backward compat when records passed)
# ---------------------------------------------------------------------------

def _filter_in_memory(
    records: list[TradeRecord],
    record_type, symbol, account_type, setup_name,
    direction, result, session, htf_bias, tag, last,
) -> list[TradeRecord]:
    out = records
    if record_type is not None:
        out = [r for r in out if r.record_type == record_type]
    if symbol is not None:
        out = [r for r in out if r.symbol.upper() == symbol.upper()]
    if account_type is not None:
        out = [r for r in out if r.account_type == account_type]
    if setup_name is not None:
        out = [r for r in out if r.setup_name == setup_name]
    if direction is not None:
        out = [r for r in out if r.direction == direction]
    if result is not None:
        out = [r for r in out if r.result == result]
    if session is not None:
        out = [r for r in out if r.session == session]
    if htf_bias is not None:
        out = [r for r in out if r.htf_bias == htf_bias]
    if tag is not None:
        out = [r for r in out if tag in r.tags]
    if last is not None:
        out = out[-last:]
    return out
