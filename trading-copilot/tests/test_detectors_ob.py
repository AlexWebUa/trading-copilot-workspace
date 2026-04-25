"""Tests for copilot/detectors/order_block.py"""

import pandas as pd
from copilot.detectors.order_block import detect_order_block


def _make_ob_df():
    """
    OB scenario:
    - 20 neutral candles
    - 1 red (bearish) candle  ← this should be the bullish OB
    - 3 large bullish candles (impulse, breaks prior high)
    - 10 follow-through candles
    """
    rows = []
    price = 100.0
    for _ in range(20):
        rows.append({"open": price, "high": price + 0.5, "low": price - 0.3, "close": price + 0.2, "volume": 500.0})
    # OB candle: red
    rows.append({"open": 100.5, "high": 101.0, "low": 99.0, "close": 99.2, "volume": 800.0})
    price = 99.2
    # Impulse: 3 large bullish candles
    for _ in range(3):
        o, c = price, price + 4.0
        rows.append({"open": o, "high": c + 1.0, "low": o - 0.2, "close": c, "volume": 3000.0})
        price = c
    # Follow-through
    for _ in range(10):
        rows.append({"open": price, "high": price + 0.5, "low": price - 0.3, "close": price + 0.3, "volume": 600.0})
        price += 0.3

    index = pd.date_range("2026-01-01", periods=len(rows), freq="1h", tz="UTC")
    df = pd.DataFrame(rows, index=index)
    df.index.name = "ts"
    return df[["open", "high", "low", "close", "volume"]].astype("float64")


def test_bullish_ob_detected():
    df = _make_ob_df()
    result = detect_order_block(df, lookback=60)
    assert result["count"] >= 1
    ob = next((o for o in result["obs"] if o["type"] == "bullish"), None)
    assert ob is not None
    assert ob["high"] > ob["low"]
    assert ob["is_mitigated"] in (True, False)


def test_no_ob_in_flat_market(flat_df):
    result = detect_order_block(flat_df)
    # Flat market: impulse threshold never met → 0 OBs
    assert result["count"] == 0


def test_insufficient_data(tiny_df):
    result = detect_order_block(tiny_df)
    assert result.get("status") == "insufficient_data"


def test_return_schema():
    df = _make_ob_df()
    result = detect_order_block(df)
    assert "obs" in result
    assert "count" in result
    for ob in result["obs"]:
        assert "type" in ob
        assert ob["type"] in ("bullish", "bearish")
        assert "high" in ob and "low" in ob
        assert "has_fvg_after" in ob
        assert "is_mitigated" in ob
