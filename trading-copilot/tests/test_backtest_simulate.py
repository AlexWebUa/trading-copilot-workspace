"""Tests for copilot/backtest/simulate.py"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from copilot.backtest.simulate import (
    _WAITING,
    _compute_atr,
    resolve_entry,
    resolve_sl,
    resolve_tp,
    simulated_exit,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_bars(
    n: int,
    base: float = 100.0,
    high_offsets: list[float] | None = None,
    low_offsets: list[float] | None = None,
) -> pd.DataFrame:
    ts = [
        datetime(2026, 4, 25, tzinfo=timezone.utc) + timedelta(hours=i)
        for i in range(n)
    ]
    rows = []
    for i in range(n):
        h_off = (high_offsets[i] if high_offsets else 1.0)
        l_off = (low_offsets[i] if low_offsets else 1.0)
        rows.append({
            "open": base,
            "high": base + h_off,
            "low": base - l_off,
            "close": base,
            "volume": 100.0,
        })
    return pd.DataFrame(rows, index=pd.DatetimeIndex(ts, tz="UTC", name="ts"))


# ---------------------------------------------------------------------------
# simulated_exit
# ---------------------------------------------------------------------------

class TestSimulatedExit:
    def test_win_long_tp_hit_first(self):
        # Bar 0: normal. Bar 2: high reaches TP.
        bars = _make_bars(5, base=100.0)
        bars.iloc[2, bars.columns.get_loc("high")] = 110.0  # TP hit at bar 2
        result, exit_price, exit_ts = simulated_exit("long", 100.0, 95.0, 108.0, bars)
        assert result == "win"
        assert exit_price == 108.0

    def test_loss_long_sl_hit(self):
        bars = _make_bars(5, base=100.0)
        bars.iloc[1, bars.columns.get_loc("low")] = 94.0  # SL hit at bar 1
        result, exit_price, exit_ts = simulated_exit("long", 100.0, 95.0, 110.0, bars)
        assert result == "loss"
        assert exit_price == 95.0

    def test_same_bar_conflict_sl_wins_long(self):
        # Bar 0 hits both SL (low=94) and TP (high=110) → SL wins (conservative)
        bars = _make_bars(1, base=100.0, high_offsets=[12.0], low_offsets=[7.0])
        result, exit_price, _ = simulated_exit("long", 100.0, 95.0, 108.0, bars)
        assert result == "loss"
        assert exit_price == 95.0

    def test_win_short_tp_hit(self):
        bars = _make_bars(5, base=100.0)
        bars.iloc[2, bars.columns.get_loc("low")] = 88.0  # TP hit for short
        result, exit_price, _ = simulated_exit("short", 100.0, 105.0, 90.0, bars)
        assert result == "win"
        assert exit_price == 90.0

    def test_loss_short_sl_hit(self):
        bars = _make_bars(5, base=100.0)
        bars.iloc[1, bars.columns.get_loc("high")] = 106.0  # SL hit for short
        result, exit_price, _ = simulated_exit("short", 100.0, 105.0, 90.0, bars)
        assert result == "loss"
        assert exit_price == 105.0

    def test_no_resolution_returns_none(self):
        # Neither SL nor TP touched in 5 bars
        bars = _make_bars(5, base=100.0, high_offsets=[0.5] * 5, low_offsets=[0.5] * 5)
        result, exit_price, exit_ts = simulated_exit("long", 100.0, 95.0, 110.0, bars)
        assert result is None
        assert exit_price is None
        assert exit_ts is None

    def test_exit_ts_is_iso_string(self):
        bars = _make_bars(3, base=100.0)
        bars.iloc[0, bars.columns.get_loc("low")] = 94.0
        _, _, exit_ts = simulated_exit("long", 100.0, 95.0, 110.0, bars)
        assert exit_ts is not None
        assert "T" in exit_ts and "Z" in exit_ts


# ---------------------------------------------------------------------------
# resolve_entry
# ---------------------------------------------------------------------------

class TestResolveEntry:
    def test_next_open_waits_one_bar(self):
        df = _make_bars(10, base=100.0)
        # Current bar is signal bar → still waiting
        ep = resolve_entry("next_open", signal_bar_idx=5, current_bar_idx=5, df=df, detector_cache={})
        assert ep is _WAITING

    def test_next_open_returns_open_at_plus_one(self):
        df = _make_bars(10, base=100.0)
        df.iloc[6, df.columns.get_loc("open")] = 101.5
        ep = resolve_entry("next_open", signal_bar_idx=5, current_bar_idx=6, df=df, detector_cache={})
        assert ep == pytest.approx(101.5)

    def test_signal_close_immediate(self):
        df = _make_bars(10, base=100.0)
        df.iloc[5, df.columns.get_loc("close")] = 99.8
        ep = resolve_entry("signal_close", signal_bar_idx=5, current_bar_idx=5, df=df, detector_cache={})
        assert ep == pytest.approx(99.8)

    def test_fvg_ce_timeout_returns_none(self):
        df = _make_bars(20, base=100.0, high_offsets=[0.5]*20, low_offsets=[0.5]*20)
        cache = {"detect_fvg": {"fvgs": [{"upper": 105.0, "lower": 103.0}]}}
        # CE = 104.0; bars never touch it (range 99.5–100.5)
        ep = resolve_entry(
            "fvg_ce", signal_bar_idx=5, current_bar_idx=5 + 11,
            df=df, detector_cache=cache, max_wait_bars=10,
        )
        assert ep is None  # timeout

    def test_fvg_ce_triggers_on_touch(self):
        df = _make_bars(20, base=100.0)
        # Bar 7 wicks to CE of FVG (upper=105, lower=103 → CE=104)
        df.iloc[7, df.columns.get_loc("high")] = 104.5
        df.iloc[7, df.columns.get_loc("low")] = 103.5
        cache = {"detect_fvg": {"fvgs": [{"upper": 105.0, "lower": 103.0}]}}
        ep = resolve_entry(
            "fvg_ce", signal_bar_idx=6, current_bar_idx=7,
            df=df, detector_cache=cache, max_wait_bars=10,
        )
        assert ep == pytest.approx(104.0)


# ---------------------------------------------------------------------------
# resolve_sl
# ---------------------------------------------------------------------------

class TestResolveSL:
    def _df(self, n=20) -> pd.DataFrame:
        return _make_bars(n, base=100.0, high_offsets=[2.0]*n, low_offsets=[2.0]*n)

    def test_atr_long(self):
        df = self._df()
        atr = _compute_atr(df)
        sl = resolve_sl("atr:1.5", 100.0, "long", df, {})
        assert sl == pytest.approx(100.0 - 1.5 * atr, rel=1e-3)

    def test_atr_short(self):
        df = self._df()
        atr = _compute_atr(df)
        sl = resolve_sl("atr:2.0", 100.0, "short", df, {})
        assert sl == pytest.approx(100.0 + 2.0 * atr, rel=1e-3)

    def test_pct_long(self):
        sl = resolve_sl("pct:1.0", 100.0, "long", self._df(), {})
        assert sl == pytest.approx(99.0, rel=1e-4)

    def test_pct_short(self):
        sl = resolve_sl("pct:2.0", 100.0, "short", self._df(), {})
        assert sl == pytest.approx(102.0, rel=1e-4)

    def test_ob_uses_ob_low(self):
        cache = {"detect_order_block": {"obs": [{"low": 97.0, "high": 99.0, "type": "bullish", "is_mitigated": False}]}}
        df = self._df()
        atr = _compute_atr(df)
        sl = resolve_sl("ob", 100.0, "long", df, cache)
        assert sl == pytest.approx(97.0 - atr * 0.05, rel=1e-3)

    def test_ob_fallback_when_no_ob(self):
        cache = {"detect_order_block": {"obs": []}}
        df = self._df()
        atr = _compute_atr(df)
        sl = resolve_sl("ob", 100.0, "long", df, cache)
        assert sl == pytest.approx(100.0 - 1.5 * atr, rel=1e-3)


# ---------------------------------------------------------------------------
# resolve_tp
# ---------------------------------------------------------------------------

class TestResolveTP:
    def _df(self, n=20) -> pd.DataFrame:
        return _make_bars(n, base=100.0, high_offsets=[2.0]*n, low_offsets=[2.0]*n)

    def test_rr_long(self):
        tp = resolve_tp("rr:2.0", 100.0, 95.0, "long", self._df(), {})
        assert tp == pytest.approx(110.0, rel=1e-4)  # entry + 2*risk

    def test_rr_short(self):
        tp = resolve_tp("rr:2.0", 100.0, 105.0, "short", self._df(), {})
        assert tp == pytest.approx(90.0, rel=1e-4)

    def test_liquidity_above_long(self):
        cache = {
            "detect_liquidity": {
                "buyside_liquidity": [{"price": 112.0}, {"price": 118.0}],
                "sellside_liquidity": [],
            }
        }
        tp = resolve_tp("liquidity", 100.0, 95.0, "long", self._df(), cache)
        assert tp == pytest.approx(112.0)

    def test_liquidity_fallback_when_empty(self):
        cache = {"detect_liquidity": {"buyside_liquidity": [], "sellside_liquidity": []}}
        tp = resolve_tp("liquidity", 100.0, 95.0, "long", self._df(), cache)
        # fallback to rr:2.0 → 100 + 2*5 = 110
        assert tp == pytest.approx(110.0, rel=1e-4)

    def test_unknown_tp_logic_fallback(self):
        tp = resolve_tp("UNKNOWN", 100.0, 95.0, "long", self._df(), {})
        assert tp == pytest.approx(110.0, rel=1e-4)
