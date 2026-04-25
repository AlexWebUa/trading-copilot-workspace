"""
Shared pytest fixtures.

OHLC fixtures are built programmatically (no live API needed).
All use the canonical schema from copilot/data/normalize.py.
"""

import numpy as np
import pandas as pd
import pytest


def _make_df(rows: list[dict], freq: str = "1h") -> pd.DataFrame:
    """Build a canonical OHLCV DataFrame from a list of row dicts."""
    index = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, index=index)
    df.index.name = "ts"
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype("float64")
    return df[["open", "high", "low", "close", "volume"]]


@pytest.fixture
def bullish_trend_df():
    """
    Bullish structure with real swing highs and lows (HH + HL zigzag).
    Three up-legs with pullbacks: forms 2+ distinct fractal highs and lows.
    """
    rows = []
    # Leg 1 up: 100 → 110
    for p in np.linspace(100, 110, 10):
        rows.append({"open": p - 0.3, "high": p + 0.5, "low": p - 0.8, "close": p, "volume": 1000.0})
    # Pullback: 110 → 106
    for p in np.linspace(110, 106, 5):
        rows.append({"open": p + 0.3, "high": p + 0.6, "low": p - 0.5, "close": p, "volume": 800.0})
    # Leg 2 up: 106 → 118 (HH vs 110, HL vs 100)
    for p in np.linspace(106, 118, 10):
        rows.append({"open": p - 0.3, "high": p + 0.5, "low": p - 0.8, "close": p, "volume": 1200.0})
    # Pullback: 118 → 113
    for p in np.linspace(118, 113, 5):
        rows.append({"open": p + 0.3, "high": p + 0.6, "low": p - 0.5, "close": p, "volume": 800.0})
    # Leg 3 up: 113 → 125 (HH vs 118, HL vs 106)
    for p in np.linspace(113, 125, 10):
        rows.append({"open": p - 0.3, "high": p + 0.5, "low": p - 0.8, "close": p, "volume": 1300.0})
    return _make_df(rows)


@pytest.fixture
def bearish_trend_df():
    """
    Bearish structure with real swing highs and lows (LH + LL zigzag).
    """
    rows = []
    # Leg 1 down: 200 → 190
    for p in np.linspace(200, 190, 10):
        rows.append({"open": p + 0.3, "high": p + 0.8, "low": p - 0.5, "close": p, "volume": 1000.0})
    # Pullback: 190 → 194
    for p in np.linspace(190, 194, 5):
        rows.append({"open": p - 0.3, "high": p + 0.5, "low": p - 0.6, "close": p, "volume": 800.0})
    # Leg 2 down: 194 → 183 (LL vs 190, LH vs 200)
    for p in np.linspace(194, 183, 10):
        rows.append({"open": p + 0.3, "high": p + 0.8, "low": p - 0.5, "close": p, "volume": 1200.0})
    # Pullback: 183 → 187
    for p in np.linspace(183, 187, 5):
        rows.append({"open": p - 0.3, "high": p + 0.5, "low": p - 0.6, "close": p, "volume": 800.0})
    # Leg 3 down: 187 → 175 (LL vs 183, LH vs 194)
    for p in np.linspace(187, 175, 10):
        rows.append({"open": p + 0.3, "high": p + 0.8, "low": p - 0.5, "close": p, "volume": 1300.0})
    return _make_df(rows)


@pytest.fixture
def fvg_bullish_df():
    """
    Contains a clear bullish FVG:
    C0: normal up candle [100, 102, 99, 101]
    C1: impulse up       [101, 108, 100.5, 107.5]  ← impulse
    C2: normal           [107, 109, 105, 108]
    FVG zone: 102 (C0 high) → 105 (C2 low)
    """
    base_rows = [{"open": 98.0, "high": 99.5, "low": 97.0, "close": 99.0, "volume": 500.0}] * 20
    fvg_rows = [
        {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 800.0},  # C0
        {"open": 101.0, "high": 108.0, "low": 100.5, "close": 107.5, "volume": 2000.0},  # C1 impulse
        {"open": 107.0, "high": 109.0, "low": 105.0, "close": 108.0, "volume": 900.0},  # C2
    ]
    follow_rows = [{"open": 108.0, "high": 110.0, "low": 107.0, "close": 109.0, "volume": 600.0}] * 10
    return _make_df(base_rows + fvg_rows + follow_rows)


@pytest.fixture
def fvg_bearish_df():
    """Contains a clear bearish FVG."""
    base_rows = [{"open": 110.0, "high": 111.0, "low": 109.0, "close": 110.5, "volume": 500.0}] * 20
    fvg_rows = [
        {"open": 109.0, "high": 110.0, "low": 107.0, "close": 107.5, "volume": 800.0},  # C0
        {"open": 107.5, "high": 108.0, "low": 101.0, "close": 101.5, "volume": 2500.0},  # C1 impulse
        {"open": 101.5, "high": 105.0, "low": 100.0, "close": 100.5, "volume": 900.0},  # C2
    ]
    # Bearish FVG: C2.high (105) < C0.low (107) → zone [105, 107]
    follow_rows = [{"open": 100.5, "high": 101.0, "low": 99.5, "close": 100.0, "volume": 600.0}] * 10
    return _make_df(base_rows + fvg_rows + follow_rows)


@pytest.fixture
def liquidity_sweep_df():
    """
    A bearish fractal high at ~120 that gets wick-swept but close stays below.
    Signals sellside liquidity taken → expect bullish continuation.
    """
    rows = []
    # Build a swing high at 120 (fractal)
    for p in [115.0, 117.0, 119.0, 120.0, 118.0, 116.0]:
        rows.append({"open": p - 0.5, "high": p + 0.5, "low": p - 1.0, "close": p, "volume": 800.0})
    # Liquidity sweep: wick to 120.8 but close at 115
    rows.append({"open": 116.0, "high": 120.8, "low": 114.5, "close": 115.2, "volume": 3000.0})
    # Recovery
    for p in [116.0, 117.5, 119.0]:
        rows.append({"open": p, "high": p + 1.0, "low": p - 0.5, "close": p + 0.8, "volume": 900.0})
    return _make_df(rows)


@pytest.fixture
def flat_df():
    """Flat / halted market — all prices identical. Edge case for detectors."""
    rows = [{"open": 50.0, "high": 50.0, "low": 50.0, "close": 50.0, "volume": 0.0}] * 30
    return _make_df(rows)


@pytest.fixture
def tiny_df():
    """Only 2 bars — below minimum for most detectors."""
    rows = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 500.0},
        {"open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 600.0},
    ]
    return _make_df(rows)
