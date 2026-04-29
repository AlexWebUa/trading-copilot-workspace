"""
Trade journal record: schema, serialization, and utility computations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytz

_KYIV_TZ = pytz.timezone("Europe/Kyiv")


@dataclass
class TradeRecord:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    record_type: str = "trade"          # "trade" | "backtest"
    ts_created: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    symbol: str = ""
    account_type: str = ""              # "demo" | "phase1" | "phase2" | "live"
    setup_name: str = ""
    direction: str = ""                 # "long" | "short"
    result: str = "pending"             # "win" | "loss" | "be" | "pending" | "missed"
    day_of_week: int = 0               # 0 = Monday
    tools_confirmed: list[str] = field(default_factory=list)
    tools_pending: list[str] = field(default_factory=list)
    tp_prices: list[float] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    ts_entry: str | None = None
    ts_exit: str | None = None
    entry_price: float | None = None
    sl_price: float | None = None
    exit_price: float | None = None
    pnl_r: float | None = None
    rr_planned: float | None = None
    session: str | None = None
    killzone: str | None = None
    htf_bias: str = ""
    notes: str = ""
    report_path: str | None = None
    partial_exits: list[dict] = field(default_factory=list)
    # Each entry: {"size_pct": float, "exit_price": float, "exit_ts": str, "pnl_r": float}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "record_type": self.record_type,
            "ts_created": self.ts_created,
            "ts_entry": self.ts_entry,
            "ts_exit": self.ts_exit,
            "symbol": self.symbol,
            "account_type": self.account_type,
            "setup_name": self.setup_name,
            "tools_confirmed": self.tools_confirmed,
            "tools_pending": self.tools_pending,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "sl_price": self.sl_price,
            "tp_prices": self.tp_prices,
            "exit_price": self.exit_price,
            "result": self.result,
            "pnl_r": self.pnl_r,
            "rr_planned": self.rr_planned,
            "session": self.session,
            "killzone": self.killzone,
            "day_of_week": self.day_of_week,
            "htf_bias": self.htf_bias,
            "notes": self.notes,
            "report_path": self.report_path,
            "tags": self.tags,
            "partial_exits": self.partial_exits,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TradeRecord":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Utility functions (used by CLI and tests)
# ---------------------------------------------------------------------------

def compute_rr(entry: float, sl: float, target: float, direction: str) -> float | None:
    """Return R-multiple for a target price given entry/SL and direction."""
    risk = abs(entry - sl)
    if risk == 0:
        return None
    if direction == "long":
        return round((target - entry) / risk, 2)
    return round((entry - target) / risk, 2)


def session_from_ts(ts_utc: str) -> str:
    """Classify a UTC ISO timestamp into a session label (Kyiv-time based)."""
    try:
        dt = datetime.fromisoformat(ts_utc.replace("Z", "+00:00"))
        local = dt.astimezone(_KYIV_TZ)
        h = local.hour
    except (ValueError, AttributeError):
        return "unknown"

    if 2 <= h < 9:
        return "asia"
    if 9 <= h < 12:
        return "london_open"
    if 12 <= h < 15:
        return "london"
    if 15 <= h < 17:
        return "ny_am"
    if 17 <= h < 20:
        return "ny_pm"
    return "off_hours"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(raw: str) -> str:
    """Accept 'now', ISO strings, or 'YYYY-MM-DD HH:MM' → ISO UTC string."""
    if raw.lower() == "now":
        return now_utc_iso()
    raw = raw.strip()
    # Try ISO with Z or offset
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    # Already has offset info
    try:
        dt = datetime.fromisoformat(raw)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return raw  # return as-is; let the user fix it
