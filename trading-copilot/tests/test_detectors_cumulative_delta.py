"""Tests for copilot/detectors/cumulative_delta.py"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from copilot.detectors.cumulative_delta import detect_cumulative_delta


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_df(
    bars: int = 20,
    base_price: float = 100.0,
    deltas: list[float] | None = None,
    price_offset: list[float] | None = None,
) -> pd.DataFrame:
    """Build OHLCV + delta columns with controlled values."""
    ts = [
        datetime(2026, 4, 25, 9, 0, tzinfo=timezone.utc) + timedelta(hours=i)
        for i in range(bars)
    ]
    deltas = deltas or [10.0] * bars
    price_offset = price_offset or [0.0] * bars

    total_vol = 100.0
    rows = []
    for i in range(bars):
        p = base_price + price_offset[i]
        d = deltas[i]
        buy = (total_vol + d) / 2
        sell = total_vol - buy
        rows.append({
            "open": p,
            "high": p + 1.0,
            "low": p - 1.0,
            "close": p,
            "volume": total_vol,
            "buy_vol": buy,
            "sell_vol": sell,
            "delta": d,
        })

    return pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))


# ---------------------------------------------------------------------------
# Basic delta computation
# ---------------------------------------------------------------------------

def test_positive_delta_trend():
    df = _make_df(bars=20, deltas=[20.0] * 20)
    result = detect_cumulative_delta(df, period="all")
    assert result["delta_trend"] == "positive"
    assert result["session_delta"] > 0


def test_negative_delta_trend():
    df = _make_df(bars=20, deltas=[-20.0] * 20)
    result = detect_cumulative_delta(df, period="all")
    assert result["delta_trend"] == "negative"
    assert result["session_delta"] < 0


def test_neutral_delta_trend():
    # All-zero delta → CD stays at 0 → slope == 0 → neutral
    deltas = [0.0] * 20
    df = _make_df(bars=20, deltas=deltas)
    result = detect_cumulative_delta(df, period="all")
    assert result["delta_trend"] == "neutral"


def test_session_delta_value():
    df = _make_df(bars=10, deltas=[5.0] * 10)
    result = detect_cumulative_delta(df, period="all")
    # CD should be 50.0 at the end (10 bars × 5.0 each)
    assert result["session_delta"] == pytest.approx(50.0, abs=0.01)


def test_bars_output_capped_at_50():
    df = _make_df(bars=80, deltas=[1.0] * 80)
    result = detect_cumulative_delta(df, period="all")
    assert len(result["bars"]) <= 50


def test_bars_contain_required_keys():
    df = _make_df(bars=5, deltas=[3.0] * 5)
    result = detect_cumulative_delta(df, period="all")
    bar = result["bars"][0]
    assert "ts" in bar
    assert "delta" in bar
    assert "cumulative" in bar


# ---------------------------------------------------------------------------
# P0-4 quarantine — broken signals must NOT appear in output
# ---------------------------------------------------------------------------

def test_divergence_and_sweep_signals_removed():
    """June 2026 audit: divergence and sweep-confirmation logic fired on noise
    and was removed pending a swing-to-swing rewrite (P0-5). The output must
    not contain those keys, even on data that used to trigger them."""
    # Fixture that used to produce a bearish divergence
    price_offsets = [0.0] * 18 + [0.5, 2.0]
    deltas = [10.0] * 18 + [10.0, -15.0]
    df = _make_df(bars=20, deltas=deltas, price_offset=price_offsets)
    result = detect_cumulative_delta(df, period="all")

    assert "divergences" not in result
    assert "sweep_confirmation" not in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_insufficient_data_too_few_bars():
    df = _make_df(bars=3)
    result = detect_cumulative_delta(df, period="all")
    assert result["status"] == "insufficient_data"


def test_missing_buy_vol_column():
    df = _make_df(bars=20)
    df = df.drop(columns=["buy_vol", "sell_vol", "delta"])
    result = detect_cumulative_delta(df)
    assert result["status"] == "insufficient_data"
    assert "buy_vol" in result["reason"]


def test_period_all_uses_full_df():
    df = _make_df(bars=30, deltas=[5.0] * 30)
    result = detect_cumulative_delta(df, period="all")
    assert result["period"] == "all"
    assert len(result["bars"]) == 30


def test_output_keys_present():
    df = _make_df(bars=20)
    result = detect_cumulative_delta(df, period="all")
    assert "session_delta" in result
    assert "delta_trend" in result
    assert "bars" in result
    assert result["delta_trend"] in ("positive", "negative", "neutral")
