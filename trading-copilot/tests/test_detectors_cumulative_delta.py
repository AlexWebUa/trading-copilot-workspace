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
# P0-5 — divergence at the confirmed price extreme (probe 3 fixture)
# ---------------------------------------------------------------------------

def _bar(o, h, l, c, delta):
    buy = (100.0 + delta) / 2
    return {
        "open": o, "high": h, "low": l, "close": c, "volume": 100.0,
        "buy_vol": buy, "sell_vol": 100.0 - buy, "delta": delta,
    }


def _mk(rows):
    ts = [
        datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
        for i in range(len(rows))
    ]
    return pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))


def test_bearish_divergence_at_confirmed_extreme():
    """Probe 3 (June 2026): price prints its highest high two bars back while
    CD peaked earlier and was falling — divergence must fire even though the
    LAST bar is not the extreme (the old code only looked at the last bar)."""
    rows = [_bar(100, 101, 99, 100.5, 10) for _ in range(20)]
    rows.append(_bar(100.5, 105, 100.4, 104.5, 500))   # push high, strong delta
    rows.append(_bar(104.5, 105.2, 103.0, 103.5, 50))  # top 1, CD peaks (750)
    rows.append(_bar(103.5, 105.3, 103.2, 103.6, -200))  # top 2: HH, CD 550 < 750
    rows.append(_bar(103.6, 103.8, 102.5, 102.8, -50))
    rows.append(_bar(102.8, 103.0, 102.0, 102.2, -30))   # last bar, not the extreme
    result = detect_cumulative_delta(_mk(rows), period="all")

    bearish = [d for d in result["divergences"] if d["type"] == "bearish"]
    assert len(bearish) == 1
    assert bearish[0]["price_high"] == pytest.approx(105.3, abs=0.01)
    assert bearish[0]["context"] == "price_new_high_cd_falling"


def test_no_divergence_when_cd_confirms_the_high():
    """Aligned trend: CD makes its maximum AT the price extreme → no signal."""
    rows = [_bar(100 + i, 101 + i, 99 + i, 100.5 + i, 10) for i in range(20)]
    result = detect_cumulative_delta(_mk(rows), period="all")
    assert result["divergences"] == []


def test_breakout_not_labeled_sweep():
    """Probe 2 (June 2026): a bar that CLOSES above prior highs on positive
    delta is a breakout, not a sweep — no sweep_confirmation."""
    rows = [_bar(100 + i*0.1, 100.5 + i*0.1, 99.5 + i*0.1, 100.2 + i*0.1, 60)
            for i in range(30)]
    rows.append(_bar(103.2, 106.02, 103.0, 106.0, 60))  # closes at the top
    result = detect_cumulative_delta(_mk(rows), period="all")
    assert "sweep_confirmation" not in result


def test_pool_sweep_on_selling_flow_is_manipulation():
    """A wick raid above a confirmed swing high that closes back below it,
    printed on net-selling delta → confirmed_manipulation=True."""
    rows = [_bar(100, 101, 99, 100.5, 10) for _ in range(10)]
    rows.append(_bar(100.5, 104, 100.4, 103.5, 10))          # swing high 104
    rows += [_bar(103.5, 103.8, 101.0, 101.5, 10) for _ in range(5)]
    rows.append(_bar(101.5, 104.6, 101.3, 101.8, -40))       # wick sweep, sellers
    rows += [_bar(101.8, 102.2, 101.2, 101.6, 5) for _ in range(3)]
    result = detect_cumulative_delta(_mk(rows), period="all")

    sweep = result.get("sweep_confirmation")
    assert sweep is not None
    assert sweep["sweep_side"] == "buyside"
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
    assert "bars" in result
    assert result["delta_trend"] in ("positive", "negative", "neutral")
