"""Tests for detect_breaker_block."""

import numpy as np
import pandas as pd
import pytest

from copilot.detectors.breaker_block import detect_breaker_block


def _make_df(rows: list[dict], freq: str = "1h") -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, index=index)
    df.index.name = "ts"
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype("float64")
    return df[["open", "high", "low", "close", "volume"]]


def _flat(p: float, n: int = 1) -> list[dict]:
    return [{"open": p, "high": p + 0.5, "low": p - 0.5, "close": p, "volume": 500.0}] * n


def _make_bearish_breaker_fixture() -> pd.DataFrame:
    """
    Bullish OB (bearish C0 before bullish impulse) that gets fully pierced downward
    → becomes a Bearish Breaker Block.

    C0 body: [101, 103] (bearish: open=103, close=101)
    C1 impulse: close at 110 (closes above 103)  → Bullish OB formed at [101, 103]
    Later: price closes at 99 (below OB low = 101) → breaker formed
    Recovery: wicks back to 101 but doesn't close above 103 → tested, still active
    """
    rows = _flat(100, 15)

    # Bullish OB: bearish candle + bullish impulse
    rows.append({"open": 103.0, "high": 103.5, "low": 100.5, "close": 101.0, "volume": 1000.0})  # C0 bearish body [101,103]
    rows.append({"open": 101.0, "high": 112.0, "low": 100.5, "close": 111.0, "volume": 4000.0})  # C1 bullish impulse, range=11.5

    # Holding above
    rows += _flat(111, 5)

    # Full pierce: close below OB low (101)
    rows.append({"open": 110.0, "high": 110.5, "low": 98.0, "close": 99.0, "volume": 5000.0})

    # Recovery: wick up to 101.5 (into breaker zone) but close stays below 103
    rows.append({"open": 99.0, "high": 102.0, "low": 98.5, "close": 100.5, "volume": 2000.0})
    rows += _flat(100, 5)

    return _make_df(rows)


def _make_bullish_breaker_fixture() -> pd.DataFrame:
    """
    Bearish OB (bullish C0 before bearish impulse) that gets fully pierced upward
    → becomes a Bullish Breaker Block.

    C0 body: [108, 110] (bullish: open=108, close=110)
    C1 impulse: close at 100 (below 108)  → Bearish OB at [108, 110]
    Later: price closes at 112 (above OB high = 110) → breaker formed
    Consolidation below 108 → tested from below
    """
    rows = _flat(110, 15)

    rows.append({"open": 108.0, "high": 110.5, "low": 107.5, "close": 110.0, "volume": 1000.0})  # C0 bullish [108,110]
    rows.append({"open": 110.0, "high": 110.5, "low": 97.0, "close": 98.0, "volume": 4500.0})    # C1 bearish impulse

    rows += _flat(98, 5)

    # Full pierce: close above OB high (110)
    rows.append({"open": 99.0, "high": 113.0, "low": 99.0, "close": 112.0, "volume": 5000.0})

    # Consolidation near 110 (testing the breaker from above)
    rows.append({"open": 112.0, "high": 112.5, "low": 109.5, "close": 111.0, "volume": 2000.0})
    rows += _flat(111, 5)

    return _make_df(rows)


def _make_no_pierce_fixture() -> pd.DataFrame:
    """Bullish OB that is mitigated (touched 50%) but never fully pierced below ob_low → no breaker."""
    rows = _flat(100, 15)

    rows.append({"open": 103.0, "high": 103.5, "low": 100.5, "close": 101.0, "volume": 1000.0})
    rows.append({"open": 101.0, "high": 112.0, "low": 100.5, "close": 111.0, "volume": 4000.0})

    # Partial retrace: only touches midpoint (102), never closes below ob_low (101)
    rows += _flat(111, 3)
    rows.append({"open": 111.0, "high": 111.5, "low": 101.5, "close": 106.0, "volume": 2000.0})  # wick to 101.5 (above 101)
    rows += _flat(106, 5)

    return _make_df(rows)


class TestDetectBreakerBlock:
    def test_bearish_breaker_detected(self):
        df = _make_bearish_breaker_fixture()
        result = detect_breaker_block(df)

        assert result["count"] > 0
        breaker = result["breakers"][0]
        assert breaker["type"] == "bearish"
        assert breaker["original_ob_type"] == "bullish"

    def test_bullish_breaker_detected(self):
        df = _make_bullish_breaker_fixture()
        result = detect_breaker_block(df)

        assert result["count"] > 0
        breaker = result["breakers"][0]
        assert breaker["type"] == "bullish"
        assert breaker["original_ob_type"] == "bearish"

    def test_no_breaker_when_not_fully_pierced(self):
        df = _make_no_pierce_fixture()
        result = detect_breaker_block(df)
        # No bar closed below ob_low → no breaker
        assert result["count"] == 0

    def test_insufficient_data(self, tiny_df):
        result = detect_breaker_block(tiny_df)
        assert result["status"] == "insufficient_data"

    def test_flat_no_crash(self, flat_df):
        result = detect_breaker_block(flat_df)
        assert "breakers" in result
