"""Tests for detect_rejection_block."""

import numpy as np
import pandas as pd
import pytest

from copilot.detectors.rejection_block import detect_rejection_block


def _make_df(rows: list[dict], freq: str = "1h") -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, index=index)
    df.index.name = "ts"
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype("float64")
    return df[["open", "high", "low", "close", "volume"]]


def _flat(p: float, n: int = 1) -> list[dict]:
    return [{"open": p, "high": p + 0.5, "low": p - 0.5, "close": p, "volume": 500.0}] * n


def _make_bearish_rejection_fixture() -> pd.DataFrame:
    """
    C1: strong bullish candle open=100, close=106 (body [100, 106], size=6)
    C2: close at 98 < C1 body low (100) → bearish rejection block zone [100, 106]
    """
    rows = _flat(100, 20)

    rows.append({"open": 100.0, "high": 107.0, "low": 99.5, "close": 106.0, "volume": 2000.0})  # C1 bullish
    rows.append({"open": 106.0, "high": 106.5, "low": 97.0, "close": 97.5, "volume": 3000.0})   # C2: close < 100

    # Price stays below zone
    rows += _flat(97, 10)

    return _make_df(rows)


def _make_bullish_rejection_fixture() -> pd.DataFrame:
    """
    C1: strong bearish candle open=110, close=104 (body [104, 110], size=6)
    C2: close at 112 > C1 body high (110) → bullish rejection block zone [104, 110]
    """
    rows = _flat(110, 20)

    rows.append({"open": 110.0, "high": 110.5, "low": 103.5, "close": 104.0, "volume": 2000.0})  # C1 bearish
    rows.append({"open": 104.0, "high": 113.0, "low": 103.5, "close": 112.0, "volume": 3000.0})  # C2: close > 110

    rows += _flat(112, 10)

    return _make_df(rows)


def _make_no_engulf_fixture() -> pd.DataFrame:
    """C2 doesn't fully engulf C1 body → no rejection block."""
    rows = _flat(100, 20)

    rows.append({"open": 100.0, "high": 107.0, "low": 99.5, "close": 106.0, "volume": 2000.0})  # C1 bullish
    # C2 closes at 101 — below C1 close but NOT below C1 open (100)
    rows.append({"open": 106.0, "high": 106.5, "low": 100.2, "close": 101.0, "volume": 1500.0})

    rows += _flat(101, 10)

    return _make_df(rows)


def _make_small_body_fixture() -> pd.DataFrame:
    """C1 has tiny body (below min_body_atr threshold) → should be filtered out."""
    rows = _flat(100, 20)

    rows.append({"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.1, "volume": 100.0})  # C1: tiny body 0.1
    rows.append({"open": 100.1, "high": 100.2, "low": 98.0, "close": 98.5, "volume": 500.0})   # C2: below C1 open

    rows += _flat(98, 10)

    return _make_df(rows)


class TestDetectRejectionBlock:
    def test_bearish_rejection_detected(self):
        df = _make_bearish_rejection_fixture()
        result = detect_rejection_block(df)

        assert result["count"] > 0
        block = result["blocks"][0]
        assert block["type"] == "bearish"
        assert block["low"] == pytest.approx(100.0, abs=0.5)
        assert block["high"] == pytest.approx(106.0, abs=0.5)

    def test_bullish_rejection_detected(self):
        df = _make_bullish_rejection_fixture()
        result = detect_rejection_block(df)

        assert result["count"] > 0
        block = result["blocks"][0]
        assert block["type"] == "bullish"
        assert block["high"] == pytest.approx(110.0, abs=0.5)
        assert block["low"] == pytest.approx(104.0, abs=0.5)

    def test_no_engulf_no_block(self):
        df = _make_no_engulf_fixture()
        result = detect_rejection_block(df)
        assert result["count"] == 0

    def test_small_body_filtered_out(self):
        df = _make_small_body_fixture()
        result = detect_rejection_block(df, min_body_atr=0.3)
        # body = 0.1, atr ~1.0, so body/atr ≈ 0.1 < 0.3 threshold → filtered
        assert result["count"] == 0

    def test_insufficient_data(self, tiny_df):
        result = detect_rejection_block(tiny_df)
        assert result["status"] == "insufficient_data"

    def test_flat_market_no_crash(self, flat_df):
        result = detect_rejection_block(flat_df)
        assert "blocks" in result
