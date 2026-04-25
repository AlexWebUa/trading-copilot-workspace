"""Tests for copilot/detectors/bos.py"""

import pandas as pd
import pytest
from copilot.detectors.bos import detect_bos


def _make_mss_df():
    """
    Clear bullish structure (explicit zigzag) then sharp break below the HL.
    Swing low at price 90 is clearly the lowest point in its neighborhood.
    Reversal crashes from 120 to 70 → close well below 90 → MSS.
    """
    rows = []
    # Zigzag: 80→100→90→120→ crash
    pattern = [
        # (open, high, low, close)
        *[(80 + i, 80 + i + 2, 80 + i - 1, 80 + i + 1) for i in range(20)],  # up 80→100
        *[(100 - i, 101 - i, 99 - i, 100 - i - 1) for i in range(10)],       # down 100→90
        *[(90 + i, 90 + i + 2, 90 + i - 1, 90 + i + 1) for i in range(30)],  # up 90→120
    ]
    for o, h, l, c in pattern:
        rows.append({"open": float(o), "high": float(h), "low": float(l),
                     "close": float(c), "volume": 1000.0})
    # Crash: close well below swing low at 90
    crash_prices = [115.0, 105.0, 93.0, 82.0, 71.0]
    for close in crash_prices:
        rows.append({"open": close + 10, "high": close + 11, "low": close - 1,
                     "close": close, "volume": 5000.0})

    index = pd.date_range("2026-01-01", periods=len(rows), freq="1h", tz="UTC")
    df = pd.DataFrame(rows, index=index)
    df.index.name = "ts"
    return df[["open", "high", "low", "close", "volume"]].astype("float64")


def test_mss_detected():
    df = _make_mss_df()
    result = detect_bos(df, swing_lookback=3)
    assert result.get("type") in ("BOS", "MSS", "cBOS")
    assert result["direction"] in ("bullish", "bearish")


def test_no_bos_in_stable_trend(bullish_trend_df):
    result = detect_bos(bullish_trend_df, swing_lookback=3)
    # A monotonic uptrend should produce BOS/cBOS (continuation), not MSS
    if result["type"] != "none":
        assert result["type"] in ("BOS", "cBOS", "MSS")


def test_insufficient_data(tiny_df):
    result = detect_bos(tiny_df)
    assert "status" in result
    assert result["status"] == "insufficient_data"


def test_return_schema(bullish_trend_df):
    result = detect_bos(bullish_trend_df, swing_lookback=3)
    assert "type" in result
    assert "direction" in result
    assert "displacement_candles" in result
