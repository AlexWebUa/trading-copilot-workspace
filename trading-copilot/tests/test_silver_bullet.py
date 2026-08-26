"""ICT Silver Bullet — encoding guards.

The trader's 11-Aug reference trade is the acceptance criterion: it verified
exactly against futures data (pool 63863.9 = Asian low, sweep to 63820, 3m
fractal 63939, BOS close 63940, FVG 63903.8-63940.0, fill on the test at
03:12 NY, target 64148 = Asian high). Every number below comes from that trade.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from copilot.backtest.engine import BacktestEngine, _ltf_fvg_near_edge
from copilot.backtest.rules import Condition, SetupRule
from copilot.backtest.rules_silver_bullet import (
    ENTRY_MODES,
    SILVER_BULLET_RULES,
    TIMINGS,
)


class TestRuleSet:
    def test_twelve_arms_three_timings_two_models_two_sides(self):
        assert len(SILVER_BULLET_RULES) == 12
        assert set(SILVER_BULLET_RULES) == {
            f"sb_{t}_{m}_{d}"
            for t in TIMINGS for m in ENTRY_MODES for d in ("long", "short")
        }

    def test_every_rule_validates(self):
        for rule in SILVER_BULLET_RULES.values():
            rule.validate()

    def test_min_rr_is_the_setups_own_floor_not_the_frames(self):
        """1.3, deliberately not the 1.8 the rest of the research frame uses:
        Silver Bullet targets the nearest pool on purpose."""
        for rule in SILVER_BULLET_RULES.values():
            assert rule.min_rr == 1.3

    def test_timings_are_new_york_hours(self):
        assert TIMINGS == {"london": (3, 4), "nyam": (10, 11), "nypm": (14, 15)}
        for name, rule in SILVER_BULLET_RULES.items():
            assert rule.required_entry_hours_ny is not None, name
            # The Kyiv gate must NOT be set: gating the signal bar would reject
            # the reference trade, whose sweep preceded the window.
            assert rule.required_hours_kyiv is None, name

    def test_wait_window_cannot_outlive_the_timing(self):
        for rule in SILVER_BULLET_RULES.values():
            assert rule.max_entry_wait_bars_ltf * 3 <= 60

    def test_no_partials_and_no_break_even(self):
        for rule in SILVER_BULLET_RULES.values():
            assert rule.tp_levels == []
            assert rule.sl_after_tp1 is None


class TestNearestFractalTarget:
    """From the 11-Aug trade: entry 63940.0 (near edge of the FVG), stop 63820.

    Risk 120. The fractals above entry paid 0.74R / 0.97R / 1.02R / 1.62R /
    1.83R, so "literally nearest" is unreachable at the 1.3 floor and the rule
    has to mean "nearest that pays".
    """

    ENTRY, SL = 63940.0, 63820.0
    LEVELS = [64021.8, 64048.2, 64054.0, 64124.2, 64148.0]

    def _resolve(self, levels, min_rr=1.3, direction="long"):
        from copilot.backtest.simulate import resolve_tp

        registry = {
            "detect_fractals": lambda df, **kw: {
                "fractals": [
                    {"type": "swing_high" if direction == "long" else "swing_low",
                     "price": p, "is_broken": False}
                    for p in levels
                ]
            }
        }
        entry = self.ENTRY if direction == "long" else self.SL
        sl = self.SL if direction == "long" else self.ENTRY
        return resolve_tp("nearest_fractal", entry, sl, direction,
                          slice_df=None, detector_cache={}, min_rr=min_rr,
                          registry=registry)

    def test_skips_targets_below_the_floor_and_takes_the_first_that_pays(self):
        tp = self._resolve(self.LEVELS)
        assert tp == 64124.2
        rr = (tp - self.ENTRY) / (self.ENTRY - self.SL)
        assert round(rr, 2) == 1.53   # 184.2 / 120

    def test_does_not_stretch_past_the_first_paying_target(self):
        """The trader took 64148 (1.83R); the mechanical rule must still stop
        at the nearer 64124.2 — 'low hanging fruit' means nearest, not best."""
        assert self._resolve(self.LEVELS) != 64148.0

    def test_returns_none_when_nothing_pays(self):
        assert self._resolve([64021.8, 64048.2]) is None

    def test_ignores_broken_levels(self):
        from copilot.backtest.simulate import resolve_tp

        registry = {
            "detect_fractals": lambda df, **kw: {
                "fractals": [
                    {"type": "swing_high", "price": 64124.2, "is_broken": True},
                    {"type": "swing_high", "price": 64148.0, "is_broken": False},
                ]
            }
        }
        tp = resolve_tp("nearest_fractal", self.ENTRY, self.SL, "long",
                        slice_df=None, detector_cache={}, min_rr=1.3,
                        registry=registry)
        assert tp == 64148.0

    def test_ignores_fractals_of_the_wrong_side(self):
        """A long targets swing highs; swing lows above entry are not pools
        it can aim at."""
        from copilot.backtest.simulate import resolve_tp

        registry = {
            "detect_fractals": lambda df, **kw: {
                "fractals": [
                    {"type": "swing_low", "price": 64124.2, "is_broken": False},
                    {"type": "swing_high", "price": 64148.0, "is_broken": False},
                ]
            }
        }
        tp = resolve_tp("nearest_fractal", self.ENTRY, self.SL, "long",
                        slice_df=None, detector_cache={}, min_rr=1.3,
                        registry=registry)
        assert tp == 64148.0

    def test_short_side_mirrors(self):
        tp = self._resolve([63700.0, 63500.0], direction="short")
        # entry 63820, stop 63940 → risk 120; 63700 pays 1.0R, 63500 pays 2.67R
        assert tp == 63500.0


class TestFvgNearEdge:
    """The 11-Aug imbalance: 63903.8 - 63940.0, bullish."""

    def _registry(self, zones):
        return {"detect_fvg": lambda df, **kw: {"fvgs": zones}}

    def test_long_rests_the_limit_on_the_top_of_a_bullish_gap(self):
        reg = self._registry([
            {"type": "bullish", "upper": 63940.0, "lower": 63903.8,
             "is_mitigated": False, "ts": "2026-08-11T06:57:00Z"},
        ])
        assert _ltf_fvg_near_edge(None, "long", reg) == 63940.0

    def test_short_rests_the_limit_on_the_bottom_of_a_bearish_gap(self):
        reg = self._registry([
            {"type": "bearish", "upper": 63940.0, "lower": 63903.8,
             "is_mitigated": False, "ts": "2026-08-11T06:57:00Z"},
        ])
        assert _ltf_fvg_near_edge(None, "short", reg) == 63903.8

    def test_mitigated_gaps_are_not_entries(self):
        reg = self._registry([
            {"type": "bullish", "upper": 63940.0, "lower": 63903.8,
             "is_mitigated": True, "ts": "2026-08-11T06:57:00Z"},
        ])
        assert _ltf_fvg_near_edge(None, "long", reg) is None

    def test_counter_direction_gaps_are_ignored(self):
        reg = self._registry([
            {"type": "bearish", "upper": 63940.0, "lower": 63903.8,
             "is_mitigated": False, "ts": "2026-08-11T06:57:00Z"},
        ])
        assert _ltf_fvg_near_edge(None, "long", reg) is None

    def test_no_imbalance_means_no_test_entry(self):
        assert _ltf_fvg_near_edge(None, "long", self._registry([])) is None

    def test_picks_the_most_recent_gap(self):
        """detect_fvg returns its zones newest → oldest (documented in
        detectors/fvg.py), so the newest in-direction zone is the first match —
        no sorting, and no invented timestamp key."""
        reg = self._registry([
            {"type": "bullish", "upper": 63940.0, "lower": 63903.8,
             "is_mitigated": False, "formed_ts": "2026-08-11T06:57:00+00:00"},
            {"type": "bullish", "upper": 63800.0, "lower": 63700.0,
             "is_mitigated": False, "formed_ts": "2026-08-11T05:00:00+00:00"},
        ])
        assert _ltf_fvg_near_edge(None, "long", reg) == 63940.0


# ---------------------------------------------------------------------------
# Engine-level: the NY window gates the FILL, not the signal
# ---------------------------------------------------------------------------

def _frame(n, start, step_min, price=100.0, drift=0.0):
    idx = pd.date_range(start, periods=n, freq=f"{step_min}min", tz="UTC")
    base = np.full(n, price) + np.arange(n) * drift
    df = pd.DataFrame(
        {"open": base, "high": base + 1.0, "low": base - 1.0,
         "close": base, "volume": np.full(n, 1000.0)},
        index=idx,
    )
    df.index.name = "ts"
    return df.astype("float64")


class _Src:
    def __init__(self, frames):
        self._frames = frames

    def get_ohlc(self, symbol, tf, bars, start_time=None, end_time=None):
        return self._frames[tf]


def _window_rule(ny_window, **kw):
    return SetupRule(
        name="sb_window_probe",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
        entry_after="signal_close",
        sl_logic="pct:5.0",
        tp_logic="rr:50.0",     # unreachable — trades stay open, we count entries
        min_rr=1.0,
        entry_tf="3m",
        entry_after_ltf="signal_close",
        max_entry_wait_bars_ltf=500,
        # Force the trade to close so the engine cycles: with an unreachable TP
        # a single never-resolving position would make every variant report
        # exactly one trade, and the gate would look inert when it is not.
        max_bars_open=1,
        required_entry_hours_ny=ny_window,
        **kw,
    )


def _run(rule, htf, ltf):
    engine = BacktestEngine(
        source=_Src({"1h": htf, "3m": ltf}),
        detector_registry={"detect_fvg": lambda df, **k: {"count_active": 0}},
    )
    return engine.run("BTCUSDT", "1h", rule, bars=len(htf), write_journal=False)


@pytest.fixture
def frames():
    htf = _frame(120, datetime(2026, 6, 1, tzinfo=timezone.utc), 60)
    ltf = _frame(120 * 20 + 100, datetime(2026, 6, 1, tzinfo=timezone.utc), 3)
    return htf, ltf


def test_entries_land_only_inside_the_ny_window(frames):
    htf, ltf = frames
    # 10:00-11:00 New York; June → EDT = UTC-4, so 14:00-15:00 UTC.
    summary = _run(_window_rule((10, 11)), htf, ltf)
    assert summary.trades, "no entries at all — the gate is rejecting everything"
    for t in summary.trades:
        ny_hour = pd.Timestamp(t.ts_entry).tz_convert("America/New_York").hour
        assert ny_hour == 10, f"entry at {t.ts_entry} is NY hour {ny_hour}, outside 10-11"


def test_a_different_window_produces_different_entries(frames):
    htf, ltf = frames
    a = _run(_window_rule((3, 4)), htf, ltf)
    b = _run(_window_rule((14, 15)), htf, ltf)
    ts_a = {t.ts_entry for t in a.trades}
    ts_b = {t.ts_entry for t in b.trades}
    assert ts_a and ts_b
    assert not (ts_a & ts_b), "the two timings share entries — the gate is inert"


def test_without_a_window_entries_are_unconstrained(frames):
    htf, ltf = frames
    gated = _run(_window_rule((10, 11)), htf, ltf)
    free = _run(_window_rule(None), htf, ltf)
    assert free.total_trades > gated.total_trades, (
        "the NY window must reduce the entry count, otherwise it does nothing"
    )


class TestFvgRecencySelection:
    """The limit belongs on the imbalance printed during the BOS — the newest
    one. detect_fvg returns newest → oldest, and the first implementation
    sorted on a nonexistent `ts` key, so it silently took the OLDEST zone."""

    def _reg(self, zones):
        return {"detect_fvg": lambda df, **kw: {"fvgs": zones}}

    def test_newest_zone_wins_when_several_are_in_direction(self):
        zones = [
            {"type": "bullish", "upper": 63940.0, "lower": 63903.8,
             "formed_ts": "2026-08-11T06:57:00+00:00", "fill_state": "untouched"},
            {"type": "bullish", "upper": 63700.0, "lower": 63650.0,
             "formed_ts": "2026-08-11T04:03:00+00:00", "fill_state": "untouched"},
        ]
        assert _ltf_fvg_near_edge(None, "long", self._reg(zones)) == 63940.0

    def test_the_real_field_name_is_formed_ts(self):
        """Guard against re-introducing a sort on a key that does not exist."""
        import inspect

        from copilot.backtest import engine

        src = inspect.getsource(engine._ltf_fvg_near_edge)
        assert '"ts"' not in src and '"timestamp"' not in src, (
            "sorting on a key detect_fvg does not emit silently reverses the choice"
        )

    def test_counter_direction_zones_do_not_shadow_the_right_one(self):
        zones = [
            {"type": "bearish", "upper": 63981.2, "lower": 63964.9,
             "formed_ts": "2026-08-11T06:18:00+00:00", "fill_state": "IOFED"},
            {"type": "bullish", "upper": 63940.0, "lower": 63903.8,
             "formed_ts": "2026-08-11T06:57:00+00:00", "fill_state": "untouched"},
        ]
        assert _ltf_fvg_near_edge(None, "long", self._reg(zones)) == 63940.0

    def test_filled_zones_are_skipped_in_favour_of_the_next(self):
        zones = [
            {"type": "bullish", "upper": 64000.0, "lower": 63990.0,
             "formed_ts": "2026-08-11T06:57:00+00:00", "fill_state": "filled"},
            {"type": "bullish", "upper": 63940.0, "lower": 63903.8,
             "formed_ts": "2026-08-11T06:30:00+00:00", "fill_state": "untouched"},
        ]
        assert _ltf_fvg_near_edge(None, "long", self._reg(zones)) == 63940.0
