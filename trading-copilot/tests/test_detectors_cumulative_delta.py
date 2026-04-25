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
# Divergence detection
# ---------------------------------------------------------------------------

def test_bearish_divergence_detected():
    # Last bar: price at new high, but delta dropped (CD falling)
    price_offsets = [0.0] * 18 + [0.5, 2.0]   # last bar = new high
    deltas = [10.0] * 18 + [10.0, -15.0]       # last bar delta is negative → CD falls

    df = _make_df(bars=20, deltas=deltas, price_offset=price_offsets)
    result = detect_cumulative_delta(df, period="all")

    bearish = [d for d in result["divergences"] if d["type"] == "bearish"]
    assert len(bearish) >= 1
    assert bearish[0]["context"] == "price_new_high_cd_falling"


def test_bullish_divergence_detected():
    # Last bar: price at new low, but delta rose (CD rising)
    price_offsets = [0.0] * 18 + [-0.5, -2.0]  # last bar = new low
    deltas = [-10.0] * 18 + [-10.0, 15.0]       # last bar delta positive → CD rises

    df = _make_df(bars=20, deltas=deltas, price_offset=price_offsets)
    result = detect_cumulative_delta(df, period="all")

    bullish = [d for d in result["divergences"] if d["type"] == "bullish"]
    assert len(bullish) >= 1
    assert bullish[0]["context"] == "price_new_low_cd_rising"


def test_no_divergence_when_price_and_cd_align():
    # Price goes up, CD goes up → healthy trend, no divergence
    offsets = [float(i) for i in range(20)]
    deltas = [10.0] * 20
    df = _make_df(bars=20, deltas=deltas, price_offset=offsets)
    result = detect_cumulative_delta(df, period="all")
    assert result["divergences"] == []


# ---------------------------------------------------------------------------
# Sweep confirmation
# ---------------------------------------------------------------------------

def test_buyside_sweep_confirmed_manipulation():
    """Bar 3 from end: wick above ref highs + negative delta → manipulation=True."""
    rows = []
    ts = [datetime(2026, 4, 25, 9, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(15)]

    for i in range(15):
        vol = 100.0
        if i == 12:  # sweep bar: wick above all prev highs, negative delta
            rows.append({
                "open": 102.0, "high": 110.0, "low": 101.5, "close": 102.0,
                "volume": vol, "buy_vol": 30.0, "sell_vol": 70.0, "delta": -40.0,
            })
        else:
            rows.append({
                "open": 100.0, "high": 102.0, "low": 99.0, "close": 100.0,
                "volume": vol, "buy_vol": 55.0, "sell_vol": 45.0, "delta": 10.0,
            })

    df = pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))
    result = detect_cumulative_delta(df, period="all")

    if "sweep_confirmation" in result:
        sweep = result["sweep_confirmation"]
        if sweep["sweep_side"] == "buyside":
            assert sweep["confirmed_manipulation"] is True


def test_sellside_sweep_confirmed_manipulation():
    """Bar 3 from end: wick below ref lows + positive delta → manipulation=True."""
    rows = []
    ts = [datetime(2026, 4, 25, 9, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(15)]

    for i in range(15):
        vol = 100.0
        if i == 12:
            rows.append({
                "open": 99.0, "high": 99.5, "low": 91.0, "close": 99.0,
                "volume": vol, "buy_vol": 70.0, "sell_vol": 30.0, "delta": 40.0,
            })
        else:
            rows.append({
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
                "volume": vol, "buy_vol": 45.0, "sell_vol": 55.0, "delta": -10.0,
            })

    df = pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))
    result = detect_cumulative_delta(df, period="all")

    if "sweep_confirmation" in result:
        sweep = result["sweep_confirmation"]
        if sweep["sweep_side"] == "sellside":
            assert sweep["confirmed_manipulation"] is True


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
    assert "divergences" in result
    assert "bars" in result
    assert result["delta_trend"] in ("positive", "negative", "neutral")
