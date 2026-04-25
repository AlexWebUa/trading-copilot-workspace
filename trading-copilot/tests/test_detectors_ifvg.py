"""Tests for detect_ifvg (Inverted Fair Value Gap)."""

import numpy as np
import pandas as pd
import pytest

from copilot.detectors.ifvg import detect_ifvg


def _make_df(rows: list[dict], freq: str = "1h") -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, index=index)
    df.index.name = "ts"
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype("float64")
    return df[["open", "high", "low", "close", "volume"]]


def _flat(p: float, n: int = 1) -> list[dict]:
    return [{"open": p, "high": p + 0.5, "low": p - 0.5, "close": p, "volume": 500.0}] * n


def _make_bullish_fvg_then_pierce() -> pd.DataFrame:
    """
    Build a fixture with:
    1. Stable base
    2. Bullish FVG (C0 high = 102, C2 low = 105 → zone [102, 105])
    3. Price stays above for a few bars
    4. Price then CLOSES BELOW 102 (full pierce → IFVG created, now bearish resistance)
    5. Price recovers but does not close above 105 → IFVG still active
    """
    rows = _flat(100, 20)

    # FVG candles
    rows += [
        {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 800.0},   # C0  high=102
        {"open": 101.0, "high": 108.0, "low": 100.5, "close": 107.5, "volume": 2000.0}, # C1 impulse
        {"open": 107.0, "high": 109.0, "low": 105.0, "close": 108.0, "volume": 900.0},  # C2  low=105 → FVG [102,105]
    ]

    # Price stays above FVG zone
    rows += _flat(109, 5)

    # Full bearish pierce: close below 102 (below zone lower)
    rows.append({"open": 108.0, "high": 109.0, "low": 99.0, "close": 100.5, "volume": 3000.0})

    # Recovery but stays below 105 (zone upper) → IFVG active
    rows += _flat(103, 8)

    return _make_df(rows)


def _make_bearish_fvg_then_pierce() -> pd.DataFrame:
    """
    Build a fixture with:
    1. Stable base at 110
    2. Bearish FVG (C0 low = 107, C2 high = 105 → zone [105, 107])
    3. Price stays below for a few bars
    4. Price then CLOSES ABOVE 107 (full pierce → IFVG, now bullish support)
    5. Price stays below 105 × → IFVG active
    """
    rows = _flat(110, 20)

    rows += [
        {"open": 109.0, "high": 110.0, "low": 107.0, "close": 107.5, "volume": 800.0},   # C0  low=107
        {"open": 107.5, "high": 108.0, "low": 101.0, "close": 101.5, "volume": 2500.0},  # C1 impulse
        {"open": 101.5, "high": 105.0, "low": 100.0, "close": 100.5, "volume": 900.0},   # C2  high=105 → FVG [105,107]
    ]

    # Stays below zone
    rows += _flat(100, 5)

    # Bullish pierce: close above 107 (above zone upper)
    rows.append({"open": 101.0, "high": 108.5, "low": 100.5, "close": 108.0, "volume": 3000.0})

    # Recovery but stays below 105 → IFVG active as bullish support
    rows += _flat(106, 8)

    return _make_df(rows)


def _make_fvg_not_pierced() -> pd.DataFrame:
    """FVG that never gets fully pierced — should NOT appear as IFVG."""
    rows = _flat(100, 20)
    rows += [
        {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 800.0},
        {"open": 101.0, "high": 108.0, "low": 100.5, "close": 107.5, "volume": 2000.0},
        {"open": 107.0, "high": 109.0, "low": 105.0, "close": 108.0, "volume": 900.0},
    ]
    # Price stays ABOVE zone (never pierced)
    rows += _flat(109, 15)
    return _make_df(rows)


class TestDetectIfvg:
    def test_bullish_fvg_pierce_creates_bearish_ifvg(self):
        df = _make_bullish_fvg_then_pierce()
        result = detect_ifvg(df)

        assert result["count"] > 0, "Expected at least one IFVG"
        ifvg = result["ifvgs"][0]
        assert ifvg["type"] == "bearish", "Bullish FVG pierced downward → should be bearish IFVG"
        assert ifvg["upper"] == pytest.approx(105.0, abs=1.0), "Upper should match C2 low"
        assert ifvg["lower"] == pytest.approx(102.0, abs=1.0), "Lower should match C0 high"

    def test_bearish_fvg_pierce_creates_bullish_ifvg(self):
        df = _make_bearish_fvg_then_pierce()
        result = detect_ifvg(df)

        assert result["count"] > 0
        ifvg = result["ifvgs"][0]
        assert ifvg["type"] == "bullish", "Bearish FVG pierced upward → should be bullish IFVG"

    def test_unpiereced_fvg_not_in_ifvg_list(self):
        df = _make_fvg_not_pierced()
        result = detect_ifvg(df)
        assert result["count"] == 0, "Unpierced FVG should not appear as IFVG"

    def test_insufficient_data(self, tiny_df):
        result = detect_ifvg(tiny_df)
        assert result["status"] == "insufficient_data"

    def test_flat_market_no_crash(self, flat_df):
        result = detect_ifvg(flat_df)
        assert "ifvgs" in result
        assert isinstance(result["count"], int)

    def test_tested_flag_set_when_price_revisited(self):
        df = _make_bullish_fvg_then_pierce()
        result = detect_ifvg(df)
        if result["count"] > 0:
            # The recovery bars go back up to ~103, which is inside zone [102, 105]
            # → should be marked as tested
            assert result["ifvgs"][0]["is_tested"] is True
