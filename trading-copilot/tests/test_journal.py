"""
Tests for the trade journal: record serialization, writer, reader, filter, update.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from copilot.journal.record import TradeRecord, compute_rr, session_from_ts, parse_ts
from copilot.journal.writer import append_record, update_record
from copilot.journal.reader import load_all, filter_by, get_by_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_record(**kwargs) -> TradeRecord:
    defaults = dict(
        symbol="BTCUSDT",
        account_type="demo",
        setup_name="1h3m",
        direction="long",
        entry_price=67500.0,
        sl_price=67100.0,
        tp_prices=[68200.0, 68800.0],
        htf_bias="bullish",
        session="london_open",
        killzone="09:00",
        tools_confirmed=["fvg", "order_block"],
        result="pending",
    )
    defaults.update(kwargs)
    return TradeRecord(**defaults)


# ---------------------------------------------------------------------------
# TradeRecord — construction and serialization
# ---------------------------------------------------------------------------

def test_default_id_generated():
    r = TradeRecord(symbol="BTCUSDT", setup_name="1h3m", direction="long")
    assert len(r.id) == 36  # uuid4 format
    assert r.record_type == "trade"
    assert r.result == "pending"


def test_to_dict_contains_all_keys():
    r = _make_record()
    d = r.to_dict()
    expected_keys = {
        "id", "record_type", "ts_created", "ts_entry", "ts_exit",
        "symbol", "account_type", "setup_name", "tools_confirmed", "tools_pending",
        "direction", "entry_price", "sl_price", "tp_prices", "exit_price",
        "result", "pnl_r", "rr_planned", "session", "killzone",
        "day_of_week", "htf_bias", "notes", "report_path", "tags",
        "partial_exits",
    }
    assert expected_keys == set(d.keys())


def test_roundtrip_to_dict_from_dict():
    r = _make_record(
        pnl_r=1.75,
        rr_planned=1.75,
        tags=["setup_a", "kyiv_open"],
        notes="swept asia low",
    )
    restored = TradeRecord.from_dict(r.to_dict())
    assert restored.id == r.id
    assert restored.symbol == r.symbol
    assert restored.tp_prices == r.tp_prices
    assert restored.tags == r.tags
    assert restored.notes == r.notes
    assert restored.pnl_r == r.pnl_r


def test_from_dict_ignores_unknown_keys():
    r = _make_record()
    d = r.to_dict()
    d["future_field_v2"] = "some value"  # field added in future schema version
    restored = TradeRecord.from_dict(d)
    assert restored.id == r.id  # didn't crash


def test_from_dict_handles_missing_optional_fields():
    minimal = {"symbol": "ETHUSDT", "setup_name": "silver_bullet", "direction": "short"}
    r = TradeRecord.from_dict(minimal)
    assert r.symbol == "ETHUSDT"
    assert r.entry_price is None
    assert r.tags == []


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def test_compute_rr_long():
    assert compute_rr(100.0, 95.0, 115.0, "long") == 3.0


def test_compute_rr_short():
    assert compute_rr(100.0, 105.0, 90.0, "short") == 2.0


def test_compute_rr_zero_risk():
    assert compute_rr(100.0, 100.0, 115.0, "long") is None


def test_compute_rr_negative_long():
    # exit below entry for a long = loss
    assert compute_rr(100.0, 95.0, 97.0, "long") == pytest.approx(-0.6, abs=0.01)


def test_session_from_ts_london_open():
    # 09:30 Kyiv = 06:30 UTC (summer, UTC+3)
    assert session_from_ts("2026-04-25T06:30:00Z") == "london_open"


def test_session_from_ts_ny_am():
    # 15:30 Kyiv = 12:30 UTC (summer)
    assert session_from_ts("2026-04-25T12:30:00Z") == "ny_am"


def test_session_from_ts_asia():
    # 03:00 Kyiv = 00:00 UTC
    assert session_from_ts("2026-04-25T00:00:00Z") == "asia"


def test_session_from_ts_invalid():
    assert session_from_ts("not-a-timestamp") == "unknown"


def test_parse_ts_now():
    result = parse_ts("now")
    assert result.endswith("Z")
    assert "T" in result


def test_parse_ts_iso():
    result = parse_ts("2026-04-25T09:15:00Z")
    assert result == "2026-04-25T09:15:00Z"


def test_parse_ts_short_format():
    result = parse_ts("2026-04-25 09:15")
    assert result == "2026-04-25T09:15:00Z"


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def test_append_record_creates_file(tmp_path):
    p = tmp_path / "journal.db"
    r = _make_record()
    returned = append_record(r, path=p)
    assert returned == p
    assert p.exists()


def test_append_record_roundtrip(tmp_path):
    p = tmp_path / "journal.db"
    r = _make_record()
    append_record(r, path=p)
    records = load_all(path=p)
    assert len(records) == 1
    assert records[0].symbol == "BTCUSDT"
    assert records[0].setup_name == "1h3m"


def test_append_multiple_records(tmp_path):
    p = tmp_path / "journal.db"
    for i in range(3):
        append_record(_make_record(setup_name=f"setup_{i}"), path=p)
    records = load_all(path=p)
    assert len(records) == 3


def test_update_record_modifies_result(tmp_path):
    p = tmp_path / "journal.db"
    r = _make_record(result="pending")
    append_record(r, path=p)
    found = update_record(r.id, {"result": "win", "pnl_r": 1.75}, path=p)
    assert found is True
    records = load_all(path=p)
    assert records[0].result == "win"
    assert records[0].pnl_r == 1.75


def test_update_record_not_found(tmp_path):
    p = tmp_path / "journal.db"
    append_record(_make_record(), path=p)
    found = update_record("nonexistent-id", {"result": "win"}, path=p)
    assert found is False


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------

def test_load_all_empty_journal(tmp_path):
    p = tmp_path / "journal.db"
    assert load_all(path=p) == []


def test_load_all_missing_file(tmp_path):
    p = tmp_path / "nonexistent.jsonl"
    assert load_all(path=p) == []


def test_load_all_reads_records(tmp_path):
    p = tmp_path / "journal.db"
    r1 = _make_record(setup_name="1h3m")
    r2 = _make_record(setup_name="silver_bullet", direction="short")
    append_record(r1, path=p)
    append_record(r2, path=p)
    records = load_all(path=p)
    assert len(records) == 2
    assert records[0].setup_name == "1h3m"
    assert records[1].direction == "short"



def test_filter_by_result(tmp_path):
    p = tmp_path / "journal.db"
    append_record(_make_record(result="win"), path=p)
    append_record(_make_record(result="loss"), path=p)
    append_record(_make_record(result="win"), path=p)
    wins = filter_by(path=p, result="win")
    assert len(wins) == 2
    assert all(r.result == "win" for r in wins)


def test_filter_by_setup(tmp_path):
    p = tmp_path / "journal.db"
    append_record(_make_record(setup_name="1h3m"), path=p)
    append_record(_make_record(setup_name="silver_bullet"), path=p)
    results = filter_by(path=p, setup_name="1h3m")
    assert len(results) == 1
    assert results[0].setup_name == "1h3m"


def test_filter_by_last(tmp_path):
    p = tmp_path / "journal.db"
    for i in range(5):
        append_record(_make_record(setup_name=f"s{i}"), path=p)
    last3 = filter_by(path=p, last=3)
    assert len(last3) == 3
    assert last3[-1].setup_name == "s4"


def test_filter_by_tag(tmp_path):
    p = tmp_path / "journal.db"
    append_record(_make_record(tags=["kyiv", "clean"]), path=p)
    append_record(_make_record(tags=["kyiv"]), path=p)
    append_record(_make_record(tags=["other"]), path=p)
    tagged = filter_by(path=p, tag="clean")
    assert len(tagged) == 1


def test_filter_by_symbol_case_insensitive(tmp_path):
    p = tmp_path / "journal.db"
    append_record(_make_record(symbol="BTCUSDT"), path=p)
    append_record(_make_record(symbol="ETHUSDT"), path=p)
    results = filter_by(path=p, symbol="btcusdt")
    assert len(results) == 1


def test_get_by_id_found(tmp_path):
    p = tmp_path / "journal.db"
    r = _make_record()
    append_record(r, path=p)
    found = get_by_id(r.id, path=p)
    assert found is not None
    assert found.id == r.id


def test_get_by_id_partial_prefix(tmp_path):
    p = tmp_path / "journal.db"
    r = _make_record()
    append_record(r, path=p)
    found = get_by_id(r.id[:8], path=p)
    assert found is not None
    assert found.id == r.id


def test_get_by_id_not_found(tmp_path):
    p = tmp_path / "journal.db"
    append_record(_make_record(), path=p)
    assert get_by_id("00000000", path=p) is None
