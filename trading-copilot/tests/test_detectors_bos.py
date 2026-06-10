"""Tests for copilot/detectors/bos.py"""

import numpy as np
import pandas as pd
import pytest
from copilot.detectors.bos import detect_bos
from copilot.detectors.market_structure import _find_raw_swings, _deduplicate_swings


def _make_df(rows, freq="1h"):
    index = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, index=index)
    df.index.name = "ts"
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype("float64")
    return df[["open", "high", "low", "close", "volume"]]


def _cbos_reversal_df():
    """
    Bearish cBOS: pattern ["high","low","high","low"] where C > A (HH) and D < B (LL).
    H1=100 → L1=90 → H2=110 (HH) → L2=80 (LL)
    """
    rows = []
    for p in np.linspace(105, 100, 8):
        rows.append({"open": p + 0.2, "high": p + 1.0, "low": p - 1.0, "close": p, "volume": 500.0})
    for p in np.linspace(100, 90, 8):
        rows.append({"open": p + 0.2, "high": p + 1.0, "low": p - 1.0, "close": p, "volume": 500.0})
    for p in np.linspace(90, 110, 8):
        rows.append({"open": p - 0.2, "high": p + 1.0, "low": p - 1.0, "close": p, "volume": 500.0})
    for p in np.linspace(110, 80, 10):
        rows.append({"open": p + 0.2, "high": p + 1.0, "low": p - 1.0, "close": p, "volume": 500.0})
    return _make_df(rows)


def _volatile_then_quiet_df():
    """
    Bullish zigzag: volatile early candles (range ~20) then quiet late candles (range ~1).
    Rolling ATR changes significantly so break_candle_body_atr differs across events.
    """
    rows = []
    for p in np.linspace(100, 120, 8):
        rows.append({"open": p - 2, "high": p + 10, "low": p - 10, "close": p, "volume": 2000.0})
    for p in np.linspace(120, 108, 5):
        rows.append({"open": p + 2, "high": p + 10, "low": p - 10, "close": p, "volume": 2000.0})
    for p in np.linspace(108, 130, 8):
        rows.append({"open": p - 2, "high": p + 10, "low": p - 10, "close": p, "volume": 2000.0})
    for p in np.linspace(130, 127, 5):
        rows.append({"open": p + 0.1, "high": p + 0.5, "low": p - 0.5, "close": p, "volume": 500.0})
    for p in np.linspace(127, 140, 8):
        rows.append({"open": p - 0.1, "high": p + 0.5, "low": p - 0.5, "close": p, "volume": 500.0})
    return _make_df(rows)


def test_bos_bullish_detected(bullish_trend_df):
    result = detect_bos(bullish_trend_df, swing_lookback=3)
    assert result["count"] > 0
    bullish_bos = [e for e in result["events"] if e["direction"] == "bullish" and e["type"] == "BOS"]
    assert len(bullish_bos) > 0


def test_cbos_detected_on_reversal():
    df = _cbos_reversal_df()
    result = detect_bos(df, swing_lookback=3)
    cbos_events = [e for e in result["events"] if e["type"] == "cBOS"]
    assert len(cbos_events) > 0


def test_break_ts_is_after_swing_c(bullish_trend_df):
    """Break bar is found strictly after swing C — no look-ahead bias."""
    swings = _deduplicate_swings(_find_raw_swings(bullish_trend_df, 3))
    result = detect_bos(bullish_trend_df, swing_lookback=3)
    assert result["count"] > 0

    for event in result["events"]:
        if event["direction"] != "bullish":
            continue
        break_ts = pd.Timestamp(event["break_ts"])
        for w in range(len(swings) - 3):
            sA, sB, sC, sD = swings[w], swings[w + 1], swings[w + 2], swings[w + 3]
            types = [s["type"] for s in [sA, sB, sC, sD]]
            if types != ["low", "high", "low", "high"]:
                continue
            if round(sB["price"], 2) != event["broken_level"]:
                continue
            c_ts = bullish_trend_df.index[sC["idx"]]
            assert break_ts > c_ts, f"break_ts {break_ts} not after swing C {c_ts}"
            break


def test_rolling_atr_used():
    df = _volatile_then_quiet_df()
    result = detect_bos(df, swing_lookback=3)
    if result["count"] >= 2:
        atr_values = [e["break_candle_body_atr"] for e in result["events"]]
        assert len(set(atr_values)) > 1, "all break_candle_body_atr identical — rolling ATR not varying"


def test_insufficient_data(tiny_df):
    result = detect_bos(tiny_df)
    assert "status" in result
    assert result["status"] == "insufficient_data"


def test_return_schema(bullish_trend_df):
    result = detect_bos(bullish_trend_df, swing_lookback=3)
    assert "events" in result
    assert "count" in result
    assert "latest_bias" in result
    for event in result["events"]:
        for key in ("type", "direction", "broken_level", "break_ts", "break_candle_body_atr"):
            assert key in event, f"missing key '{key}' in event: {event}"
