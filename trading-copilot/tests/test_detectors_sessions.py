"""Tests for current_killzone session helper."""

from datetime import datetime
import pytz
import pytest

from copilot.detectors.sessions import current_killzone, TOOL_SCHEMA


_KYIV = pytz.timezone("Europe/Kyiv")


def _dt(hour: int, minute: int = 0) -> datetime:
    """Create a Kyiv datetime for a weekday (Monday 2026-04-20)."""
    return _KYIV.localize(datetime(2026, 4, 20, hour, minute, 0))


class TestCurrentKillzone:
    def test_london_open_killzone(self):
        result = current_killzone(_dt(9, 30))
        assert result["active_killzone"] == "London/Kyiv Open"
        assert result["in_ott_window"] is True

    def test_ny_am_killzone(self):
        result = current_killzone(_dt(15, 30))
        assert result["active_killzone"] == "NY AM"
        assert result["in_ott_window"] is True

    def test_ny_pm_killzone(self):
        result = current_killzone(_dt(17, 30))
        assert result["active_killzone"] == "NY PM"
        assert result["in_ott_window"] is False  # 17:30 is after OTT end (17:00)

    def test_outside_killzone(self):
        result = current_killzone(_dt(12, 0))
        assert result["active_killzone"] is None
        assert result["in_ott_window"] is True  # 12:00 is inside OTT (09-17)

    def test_before_ott_window(self):
        result = current_killzone(_dt(7, 0))
        assert result["in_ott_window"] is False
        assert result["active_killzone"] is None

    def test_next_killzone_populated_before_london_open(self):
        result = current_killzone(_dt(8, 0))
        assert result["next_killzone"] is not None
        assert "London" in result["next_killzone"]

    def test_tool_schema_present(self):
        assert TOOL_SCHEMA["name"] == "current_killzone"
        assert "description" in TOOL_SCHEMA
        assert "input_schema" in TOOL_SCHEMA

    def test_no_args_call_returns_valid(self):
        """Calling with no arguments should work (uses current system time)."""
        result = current_killzone()
        assert "kyiv_time" in result
        assert "active_killzone" in result
        assert "in_ott_window" in result
        assert "weekday" in result
