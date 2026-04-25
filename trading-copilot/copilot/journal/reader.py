"""
Journal queries: load all records, filter by any field combination.
"""

from __future__ import annotations

import json
from pathlib import Path

from copilot.journal.record import TradeRecord
from copilot.journal.writer import _DEFAULT_PATH


def load_all(path: Path | None = None) -> list[TradeRecord]:
    p = path or _DEFAULT_PATH
    if not p.exists():
        return []
    records: list[TradeRecord] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(TradeRecord.from_dict(json.loads(stripped)))
        except Exception:
            continue  # skip malformed lines without crashing
    return records


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
    if records is None:
        records = load_all(path=path)

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


def get_by_id(record_id: str, path: Path | None = None) -> TradeRecord | None:
    """Find a record by full or partial ID prefix."""
    for r in load_all(path=path):
        if r.id == record_id or r.id.startswith(record_id):
            return r
    return None
