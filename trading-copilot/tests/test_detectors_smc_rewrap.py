"""
Regression suite for the P0-3 smartmoneyconcepts rewrap (June 2026 audit).

Each test encodes a probe from probes/probe_detectors*.py that the old
implementations failed. If one of these breaks, a root cause from the
audit (R1 swing-dedup erasure, R2 wick-driven state, R4 sweep side
semantics) has been reintroduced.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from copilot.detectors.bos import detect_bos
from copilot.detectors.liquidity import detect_liquidity
from copilot.detectors.market_structure import detect_market_structure
from copilot.detectors.order_block import detect_order_block


def _mk(rows, freq_h: int = 1):
    ts = [
        datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i * freq_h)
        for i in range(len(rows))
    ]
    df = pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))
    if "volume" not in df.columns:
        df["volume"] = 100.0
    return df[["open", "high", "low", "close", "volume"]]


def _bar(o, h, l, c, v=100.0):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _uptrend_with_pullback():
    """Four clean up-legs with shallow pullbacks; final pullback in progress."""
    rows = []
    for leg in range(4):
        base = 100 + leg * 10
        for j in range(5):
            rows.append(_bar(base + j*2, base + j*2 + 2.2, base + j*2 - 0.4, base + j*2 + 2))
        for j in range(3):
            top = base + 10
            rows.append(_bar(top - j*1.5, top - j*1.5 + 0.5, top - j*1.5 - 1.7, top - j*1.5 - 1.5))
    last_top = 140
    for j in range(3):
        rows.append(_bar(last_top - j*1.2, last_top - j*1.2 + 0.3, last_top - j*1.2 - 1.4, last_top - j*1.2 - 1.2))
    return _mk(rows)


# ---------------------------------------------------------------------------
# market_structure (probes 1 / 18)
# ---------------------------------------------------------------------------

class TestMarketStructure:
    def test_uptrend_stays_bullish_in_pullback(self):
        """R2: a normal retracement must not read 'ranging' — only a
        confirmed close-break event changes state."""
        ms = detect_market_structure(_uptrend_with_pullback(), swing_lookback=2)
        assert ms["state"] == "bullish"
        assert ms["last_bos_type"] == "BOS"

    def test_flat_market_is_ranging(self):
        df = _mk([_bar(100, 101, 99, 100) for _ in range(40)])
        ms = detect_market_structure(df, swing_lookback=5)
        assert ms["state"] == "ranging"
        assert ms["last_bos_type"] is None

    def test_insufficient_data(self):
        df = _mk([_bar(100, 101, 99, 100) for _ in range(5)])
        ms = detect_market_structure(df, swing_lookback=5)
        assert ms["status"] == "insufficient_data"


# ---------------------------------------------------------------------------
# bos (probe 10)
# ---------------------------------------------------------------------------

class TestBos:
    def test_textbook_bullish_bos_detected(self):
        """Close above the prior swing high (102) after a higher low must emit
        a bullish BOS at that level — the old code returned noise cBOS only."""
        rows = [_bar(100, 101, 99, 100.2) for _ in range(8)]
        rows += [_bar(100, 100.4, 96.0, 96.5)]
        rows += [_bar(96.5, 97.5, 96.2, 97.2) for _ in range(3)]
        rows += [_bar(97.2, 102.0, 97.0, 101.5)]
        rows += [_bar(101.5, 101.8, 98.5, 99.0) for _ in range(3)]
        rows += [_bar(99.0, 103.5, 98.9, 103.2)]   # close 103.2 > 102
        rows += [_bar(103.2, 103.8, 102.8, 103.4) for _ in range(3)]
        r = detect_bos(_mk(rows), swing_lookback=3)

        assert any(
            e["type"] == "BOS" and e["direction"] == "bullish"
            and abs(e["broken_level"] - 102) < 0.01
            for e in r["events"]
        ), r["events"]
        assert r["latest_bias"] == "bullish"

    def test_flat_market_no_events(self):
        df = _mk([_bar(100, 101, 99, 100) for _ in range(40)])
        r = detect_bos(df, swing_lookback=5)
        assert r["events"] == []
        assert r["latest_bias"] == "none"


# ---------------------------------------------------------------------------
# order_block (probe 12 — R1)
# ---------------------------------------------------------------------------

class TestOrderBlock:
    def test_ob_found_when_pullback_low_unconfirmed(self):
        """R1: price breaks the swing high (105) before any swing low confirms
        in between. Alternation-dedup would erase the broken swing and miss
        the OB; raw chronological consumption must find the lowest-low candle
        (low 101)."""
        rows = [_bar(100, 100.8, 99.4, 100.3) for _ in range(8)]
        rows += [_bar(100.3, 105.0, 100.2, 104.5)]   # swing high 105
        rows += [_bar(104.5, 104.8, 103.0, 103.3)]
        rows += [_bar(103.3, 103.5, 101.0, 101.4)]   # lowest low 101 = the OB
        rows += [_bar(101.4, 102.5, 101.2, 102.3)]
        rows += [_bar(102.3, 106.5, 102.2, 106.2)]   # close 106.2 > 105
        rows += [_bar(106.2, 106.8, 105.8, 106.4) for _ in range(4)]
        r = detect_order_block(_mk(rows), swing_lookback=3)

        assert any(
            o["type"] == "bullish" and abs(o["low"] - 101.0) < 0.01
            for o in r["obs"]
        ), r["obs"]


# ---------------------------------------------------------------------------
# liquidity (probes 7 / 17 — R4)
# ---------------------------------------------------------------------------

def _swing_high_104_rows():
    rows = [_bar(100, 101, 99, 100.5) for _ in range(10)]
    rows += [_bar(100.5, 104, 100.4, 103.5)]                 # swing high 104
    rows += [_bar(103.5, 103.8, 101.0, 101.5) for _ in range(5)]
    return rows


class TestLiquidity:
    def test_close_through_break_is_not_a_sweep(self):
        rows = _swing_high_104_rows()
        rows += [_bar(101.5, 106, 101.4, 105.8)]             # CLOSES above 104
        rows += [_bar(105.8, 106.2, 105.0, 105.5) for _ in range(3)]
        r = detect_liquidity(_mk(rows), lookback=30)

        assert not any(
            abs(s["swept_level"] - 104) < 0.5 for s in r["recent_sweeps"]
        ), r["recent_sweeps"]

    def test_genuine_wick_sweep_is_reported(self):
        rows = _swing_high_104_rows()
        rows += [_bar(101.5, 104.6, 101.3, 101.8)]           # wick above, close back
        rows += [_bar(101.8, 102.2, 101.2, 101.6) for _ in range(3)]
        r = detect_liquidity(_mk(rows), lookback=30)

        sweeps = [
            s for s in r["recent_sweeps"]
            if s["side"] == "buyside" and abs(s["swept_level"] - 104) < 0.5
        ]
        assert len(sweeps) == 1, r["recent_sweeps"]
        assert sweeps[0]["closed_back"] is True

    def test_no_sellside_label_at_a_high_pool(self):
        """R4: a swing-HIGH pool can only be swept buyside. The old code ran
        both geometries on every level, labeling a wide bullish bar a
        'sellside sweep' of the high."""
        rows = _swing_high_104_rows()
        rows += [_bar(101.5, 106, 101.4, 105.8)]
        rows += [_bar(105.8, 106.2, 105.0, 105.5) for _ in range(3)]
        r = detect_liquidity(_mk(rows), lookback=30)

        assert not any(
            s["side"] == "sellside" and abs(s["swept_level"] - 104) < 0.5
            for s in r["recent_sweeps"]
        )

    def test_flat_market_no_pools(self):
        df = _mk([_bar(50, 50, 50, 50, v=0.0) for _ in range(30)])
        r = detect_liquidity(df)
        assert r["buyside_liquidity"] == []
        assert r["sellside_liquidity"] == []
        assert r["recent_sweeps"] == []
