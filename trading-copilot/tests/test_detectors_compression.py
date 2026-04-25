"""Tests for detect_compression (LRLR)."""

import numpy as np
import pandas as pd
import pytest

from copilot.detectors.compression import detect_compression


def _make_df(rows: list[dict], freq: str = "1h") -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, index=index)
    df.index.name = "ts"
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype("float64")
    return df[["open", "high", "low", "close", "volume"]]


def _bar(p: float, rng: float) -> dict:
    """A single candle centred at p with range rng."""
    half = rng / 2
    return {"open": p, "high": p + half, "low": p - half, "close": p, "volume": 500.0}


def _make_active_compression() -> pd.DataFrame:
    """
    LRLR sequence ending at the LAST bar → active compression.
    Ranges: 10, 8, 6, 4, 2 (5 consecutive narrowing bars).
    """
    rows = [_bar(100.0, 10.0)] * 20  # stable baseline
    # Narrowing sequence at the end
    for rng in [10.0, 8.0, 6.0, 4.0, 2.0]:
        rows.append(_bar(100.0, rng))
    return _make_df(rows)


def _make_past_compression() -> pd.DataFrame:
    """
    LRLR sequence that ended 5 bars ago.
    """
    rows = [_bar(100.0, 10.0)] * 20
    # Narrowing sequence
    for rng in [10.0, 8.0, 6.0, 4.0, 2.0]:
        rows.append(_bar(100.0, rng))
    # Then expansion resumes
    rows += [_bar(100.0, 10.0)] * 5
    return _make_df(rows)


def _make_no_compression() -> pd.DataFrame:
    """Randomly varying ranges — no sustained narrowing."""
    rows = []
    rng_seq = [5.0, 7.0, 4.0, 8.0, 6.0, 9.0, 3.0, 5.0, 7.0, 4.0]
    for rng in rng_seq * 5:
        rows.append(_bar(100.0, rng))
    return _make_df(rows)


def _make_monotone_compression() -> pd.DataFrame:
    """Continuously narrowing ranges — should be detected."""
    rows = [_bar(100.0, 10.0)] * 10
    for rng in [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0]:
        rows.append(_bar(100.0, rng))
    return _make_df(rows)


class TestDetectCompression:
    def test_active_compression_detected(self):
        df = _make_active_compression()
        result = detect_compression(df, min_bars=3)

        assert result["count"] > 0
        assert result["active"] is True
        comp = result["compressions"][0]
        assert comp["is_active"] is True
        assert comp["bars"] >= 3

    def test_past_compression_detected(self):
        df = _make_past_compression()
        result = detect_compression(df, min_bars=3)

        assert result["count"] > 0
        comp = result["compressions"][0]
        assert comp["bars_since_end"] > 0
        assert comp["is_active"] is False

    def test_no_compression_when_ranges_vary(self):
        df = _make_no_compression()
        result = detect_compression(df, min_bars=4)
        # No 4+ consecutive narrowing bars → no result
        assert result["count"] == 0

    def test_squeeze_ratio_reflects_contraction(self):
        df = _make_active_compression()
        result = detect_compression(df, min_bars=3)

        if result["count"] > 0:
            comp = result["compressions"][0]
            # start_range should be larger than end_range
            assert comp["start_range"] > comp["end_range"]
            assert comp["squeeze_ratio"] > 1.0

    def test_monotone_compression_detected(self):
        df = _make_monotone_compression()
        result = detect_compression(df, min_bars=3)
        assert result["count"] > 0

    def test_insufficient_data(self, tiny_df):
        result = detect_compression(tiny_df, min_bars=4)
        assert result["status"] == "insufficient_data"

    def test_flat_market_handled(self, flat_df):
        # All ranges are 0 — no narrowing possible
        result = detect_compression(flat_df)
        assert "compressions" in result
        assert isinstance(result["active"], bool)
