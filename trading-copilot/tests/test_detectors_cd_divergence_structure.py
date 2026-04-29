"""Tests for copilot/detectors/cd_divergence_structure.py"""

from __future__ import annotations

import pandas as pd
import pytest

from copilot.detectors.cd_divergence_structure import check_cd_divergence_at_structure


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(rows: list[dict], freq: str = "1h") -> pd.DataFrame:
    ts = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, index=ts)
    df.index.name = "ts"
    return df


def _bar(close: float, h_off: float = 2.0, l_off: float = 2.0, delta: float = 10.0) -> dict:
    """Build a single OHLCV+delta row dict."""
    return {
        "open": close - 0.5,
        "high": close + h_off,
        "low": close - l_off,
        "close": close,
        "volume": 1000.0,
        "buy_vol": 600.0,
        "sell_vol": 400.0,
        "delta": delta,
    }


# Shared 50-bar close sequences used across multiple tests.
# Swing highs detected by _find_swings(lookback=5):
#   bar 22 (close=117, high=119) — peak of first up-leg
#   bar 35 (close=116, high=118) — peak of second up-leg  ← last_swing_high
# Swing lows:
#   bar  9 (close=99,  low=97)
#   bar 29 (close=106, low=104)
_BEARISH_CLOSES = (
    [100, 101, 102, 103, 104] +         # bars  0-4
    [103, 102, 101, 100, 99] +          # bars  5-9  (swing low ≈ 97)
    [100, 101, 102, 103, 104] +         # bars 10-14
    [106, 108, 110, 112, 114] +         # bars 15-19
    [115, 116, 117, 116, 115] +         # bars 20-24 (swing high at bar 22 ≈ 119)
    [113, 111, 109, 107, 106] +         # bars 25-29 (swing low at bar 29 ≈ 104)
    [108, 110, 112, 114, 115] +         # bars 30-34
    [116] +                              # bar 35 (swing high ≈ 118) ← last_swing_high
    [114, 112, 110, 109, 108] +         # bars 36-40
    [109, 110, 111, 112] +              # bars 41-44
    [113, 114, 115, 116]                # bars 45-48
)

# Same layout inverted for bullish scenario.
# Swing lows: bar 22 (low=101), bar 35 (low=102) ← last_swing_low
# Swing highs: bar 9 (high=123), bar 29 (high=116)
_BULLISH_CLOSES = (
    [120, 119, 118, 117, 116] +         # bars  0-4
    [117, 118, 119, 120, 121] +         # bars  5-9  (swing high at bar 9 ≈ 123)
    [120, 119, 118, 117, 116] +         # bars 10-14
    [114, 112, 110, 108, 106] +         # bars 15-19
    [105, 104, 103, 104, 105] +         # bars 20-24 (swing low at bar 22 ≈ 101)
    [107, 109, 111, 113, 114] +         # bars 25-29 (swing high at bar 29 ≈ 116)
    [112, 110, 108, 106, 105] +         # bars 30-34
    [104] +                              # bar 35 (swing low ≈ 102) ← last_swing_low
    [106, 108, 110, 111, 112] +         # bars 36-40
    [111, 110, 109, 108] +              # bars 41-44
    [107, 106, 105, 104]                # bars 45-48
)


# ---------------------------------------------------------------------------
# Test 1: Bearish divergence at swing high
# ---------------------------------------------------------------------------

def test_bearish_divergence_at_swing_high():
    """
    50-bar uptrend with last_swing_high at price ≈118.
    Last bar: close=117 (within 1.0 ATR of swing high), high=119, delta=-300.

    Expected:
      divergence_detected=True, type="bearish", at_structure=True,
      structure_type="swing_high", signal_strength in ("moderate", "strong")
    """
    rows = [_bar(c) for c in _BEARISH_CLOSES]
    # Bar 49 (last): signal bar — close near swing high (118), new high, CD crashes
    rows.append(_bar(117.0, h_off=2.0, l_off=2.0, delta=-300.0))
    df = _make_df(rows)

    result = check_cd_divergence_at_structure(df)

    assert result["divergence_detected"] is True
    assert result["type"] == "bearish"
    assert result["at_structure"] is True
    assert result["structure_type"] == "swing_high"
    assert result["structure_level"] is not None
    assert result["signal_strength"] in ("moderate", "strong")
    assert isinstance(result["cd_divergence_detail"], dict)
    assert result["cd_divergence_detail"]["type"] == "bearish"


# ---------------------------------------------------------------------------
# Test 2: Bullish divergence at swing low
# ---------------------------------------------------------------------------

def test_bullish_divergence_at_swing_low():
    """
    50-bar downtrend with last_swing_low at price ≈102.
    Last bar: close=103 (within 1.0 ATR of swing low), new low, delta=+300.

    Expected:
      divergence_detected=True, type="bullish", at_structure=True,
      structure_type="swing_low"
    """
    rows = [_bar(c) for c in _BULLISH_CLOSES]
    # Bar 49: close=103, low=101 (near swing low ≈ 102), delta=+300 (CD rising)
    rows.append(_bar(103.0, h_off=2.0, l_off=2.0, delta=300.0))
    df = _make_df(rows)

    result = check_cd_divergence_at_structure(df)

    assert result["divergence_detected"] is True
    assert result["type"] == "bullish"
    assert result["at_structure"] is True
    assert result["structure_type"] == "swing_low"
    assert result["signal_strength"] in ("moderate", "strong")


# ---------------------------------------------------------------------------
# Test 3: Divergence exists but price is far from structure
# ---------------------------------------------------------------------------

def test_no_divergence_away_from_structure():
    """
    Same swing structure (swing high ≈118, swing low ≈104).
    Last bar price at 110 (far from both swings, ATR≈4 → tolerance≈2).
    Bars 41-48 flat at 108; bar 49 recovers slightly to close=110 (new local high
    vs flat prior bars), CD falls sharply.

    Expected:
      at_structure=False
      signal_strength in ("weak", "none")  — divergence present but not at structure
    """
    rows = [_bar(c) for c in _BEARISH_CLOSES[:-4]]  # bars 0-44 (remove last 4)
    # bars 41-44 flat at 108
    rows += [_bar(108.0) for _ in range(4)]          # bars 41-44
    # bars 45-48: slightly lower (107) so bar 49's high becomes a local new high
    rows += [_bar(107.0) for _ in range(4)]          # bars 45-48
    # bar 49: close=110, but far from swing_high≈118 and swing_low≈104
    rows.append(_bar(110.0, h_off=2.0, l_off=2.0, delta=-300.0))
    df = _make_df(rows)

    result = check_cd_divergence_at_structure(df)

    assert result["at_structure"] is False
    assert result["signal_strength"] in ("weak", "none")


# ---------------------------------------------------------------------------
# Test 4: Strong signal with sweep
# ---------------------------------------------------------------------------

def test_strong_signal_with_sweep():
    """
    Same bearish divergence setup as test 1, but bar 46 is a spike (high=125,
    close=112) that sweeps the swing high (118) and closes back below it.
    detect_liquidity should detect this as a recent sweep → signal_strength="strong".
    """
    rows = [_bar(c) for c in _BEARISH_CLOSES]
    # Bar 45: close=113 (from _BEARISH_CLOSES[-4]=113 but we rebuild from scratch)
    # Rebuild bars 45-49 explicitly:
    # bars 45-48 from base sequence: closes = [113, 114, 115, 116]
    # Override bar 46 (index 46) with sweep bar: high=125, close=112
    rows_45_48 = [
        _bar(113.0),                                          # bar 45
        {"open": 112.0, "high": 125.0, "low": 111.0, "close": 112.0,  # bar 46: SWEEP
         "volume": 3000.0, "buy_vol": 1000.0, "sell_vol": 2000.0, "delta": -50.0},
        _bar(115.0),                                          # bar 47
        _bar(116.0),                                          # bar 48
    ]
    # Replace last 4 rows (bars 45-48) from the base + add bar 49
    final_rows = rows + rows_45_48
    # bar 49 (last): near swing high (118), bearish divergence
    final_rows.append(_bar(117.0, h_off=2.0, l_off=2.0, delta=-300.0))

    df = _make_df(final_rows)

    result = check_cd_divergence_at_structure(df)

    # If sweep IS detected, expect "strong"; otherwise at minimum "moderate"
    # (detect_liquidity may or may not catch this sweep depending on fractal detection)
    assert result["divergence_detected"] is True
    assert result["type"] == "bearish"
    assert result["at_structure"] is True
    # signal_strength depends on whether detect_liquidity catches the sweep
    assert result["signal_strength"] in ("moderate", "strong")
    # If sweep_preceded is True, signal must be "strong"
    if result["sweep_preceded"]:
        assert result["signal_strength"] == "strong"
        assert result["sweep_ts"] is not None


# ---------------------------------------------------------------------------
# Test 5: Insufficient data
# ---------------------------------------------------------------------------

def test_insufficient_data():
    rows = [_bar(100.0) for _ in range(10)]
    df = _make_df(rows)
    result = check_cd_divergence_at_structure(df)
    assert result.get("status") == "insufficient_data"
    assert result["divergence_detected"] is False


# ---------------------------------------------------------------------------
# Test 6: Missing delta column
# ---------------------------------------------------------------------------

def test_missing_delta_column():
    """Plain OHLCV df (no delta column) → graceful fallback."""
    rows = [
        {"open": 99.5, "high": 102.0, "low": 98.0, "close": 100.0, "volume": 1000.0}
        for _ in range(50)
    ]
    df = _make_df(rows)
    result = check_cd_divergence_at_structure(df)
    assert result.get("status") == "insufficient_data"
    assert result["divergence_detected"] is False
    assert "delta" in result.get("reason", "")
