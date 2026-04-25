"""
Session and killzone time helpers.
All logic is timezone-aware (Europe/Kyiv).

Exposed as MCP/CLI tool via TOOL_SCHEMA so Claude can ask "what time is it /
what killzone are we in?" without relying on its own (often stale) clock.
"""

from datetime import datetime, time
import pytz

TOOL_SCHEMA = {
    "name": "current_killzone",
    "description": (
        "Return the current Kyiv time, active killzone (if any), OTT window state, "
        "and next upcoming killzone. "
        "Use at the start of any analysis to check session context — "
        "setups only trigger during active killzones (09:00, 15:00, 17:00 Kyiv)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

_KYIV_TZ = pytz.timezone("Europe/Kyiv")

# Killzone windows (local Kyiv time)
_KILLZONES: list[tuple[time, time, str]] = [
    (time(9, 0), time(10, 0), "London/Kyiv Open"),
    (time(15, 0), time(16, 0), "NY AM"),
    (time(17, 0), time(18, 0), "NY PM"),
]
_OTT_START = time(9, 0)
_OTT_END = time(17, 0)


def now_kyiv() -> datetime:
    return datetime.now(_KYIV_TZ)


def current_killzone(dt: datetime | None = None) -> dict:
    """Return info about the current session/killzone state."""
    dt = (dt or now_kyiv()).astimezone(_KYIV_TZ)
    local = dt.time().replace(tzinfo=None)

    active_kz = None
    for start, end, name in _KILLZONES:
        if start <= local < end:
            active_kz = name
            break

    in_ott = _OTT_START <= local < _OTT_END

    return {
        "kyiv_time": dt.strftime("%H:%M"),
        "weekday": dt.strftime("%A"),
        "in_ott_window": in_ott,
        "active_killzone": active_kz,
        "next_killzone": _next_killzone(local),
        "is_friday": dt.weekday() == 4,
    }


def _next_killzone(local: time) -> str | None:
    for start, _, name in _KILLZONES:
        if local < start:
            return f"{name} @ {start.strftime('%H:%M')} Kyiv"
    return None
