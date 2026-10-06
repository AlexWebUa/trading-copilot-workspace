"""Detector-combination simulator — every rule that decides a trade, on built candles.

The base fixture is the trader's example of 2026-10-03, long side:

    bars 0-19   flat, lows 99.4            no fractals: equal lows are not strict
    bar 20      low 99.2                   5-candle fractal low, known at bar 22
    bars 21-24  flat
    bar 25      low 99.0, close 99.6       wick through the pool, close back: sweep
    bar 26      impulse to 100.9           C1
    bar 27      low 100.0 > high[25] 99.8  C2: bullish FVG 99.8-100.0, known here
    bar 28      low 99.9                   retest: limit at 100.0 fills
    bar 29      high 102.5                 target 100 + 2 x (100 - 99) = 102

Entry 100, stop 99, exit 102 is the engine's own cost example: +2R gross, 6 bps a
side on 100 and 102 of notional against a risk of 1 nets 1.8788R.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from copilot.backtest.combo import (
    CHAINS, ComboParams, FlowStreams, _bars, _session_pools, flow_streams, release_bias,
    simulate, sweep_bars,
)
from copilot.detectors.smc_lib import true_range_atr

Row = tuple[float, float, float, float]

FLAT: Row = (99.5, 99.8, 99.4, 99.5)
PIVOT: Row = (99.5, 99.8, 99.2, 99.5)
SWEEP: Row = (99.5, 99.8, 99.0, 99.6)
IMPULSE: Row = (99.6, 100.9, 99.5, 100.8)
C2: Row = (100.8, 101.2, 100.0, 101.0)
RETEST: Row = (101.0, 101.1, 99.9, 100.5)
RALLY: Row = (100.5, 102.5, 100.4, 102.3)
ABOVE: Row = (101.0, 101.3, 100.6, 101.0)      # hovers over the gap, touches nothing

T = 25              # the sweep bar in the base fixture


def _df(rows: list[Row], freq: str = "5min", start: str = "2026-01-05 00:00") -> pd.DataFrame:
    # unit="ms" on purpose: the data layer delivers datetime64[ms].
    index = pd.date_range(start, periods=len(rows), freq=freq, tz="UTC", name="ts", unit="ms")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)
    df["volume"] = 1.0
    return df


def _lead() -> list[Row]:
    return [FLAT] * 20 + [PIVOT] + [FLAT] * 4


def _base(*tail: Row) -> list[Row]:
    return _lead() + [SWEEP, IMPULSE, C2, *tail]


def _mirror(rows: list[Row]) -> list[Row]:
    return [(200 - o, 200 - lo, 200 - h, 200 - c) for o, h, lo, c in rows]


class TestTraderExample:
    def test_sweep_fvg_retest_takes_two_r(self):
        res = simulate(_df(_base(RETEST, RALLY)))
        assert len(res.trades) == 1
        t = res.trades.iloc[0]
        assert (t["known_i"], t["entry_i"], t["exit_i"]) == (T + 2, T + 3, T + 4)
        assert (t["entry"], t["stop"], t["tp"], t["exit"]) == (100.0, 99.0, 102.0, 102.0)
        assert t["exit_kind"] == "tp"
        assert t["gross_r"] == pytest.approx(2.0)
        assert t["r"] == pytest.approx(1.8788)
        assert not t["floor_hit"]
        assert res.funnel["sweeps"] == 1 and res.funnel["filled"] == 1

    def test_short_side_is_the_mirror(self):
        res = simulate(_df(_mirror(_base(RETEST, RALLY))), ComboParams(side="short"))
        assert len(res.trades) == 1
        t = res.trades.iloc[0]
        assert (t["entry"], t["stop"], t["exit"]) == (100.0, 101.0, 98.0)
        assert t["gross_r"] == pytest.approx(2.0)
        # 6 bps on 100 + 98 of notional, not on 100 + 102
        assert t["cost_r"] == pytest.approx(0.1188)

    def test_long_pattern_is_not_a_short_trade(self):
        res = simulate(_df(_base(RETEST, RALLY)), ComboParams(side="short"))
        assert res.trades.empty


class TestSweep:
    def test_wick_and_close_back_is_a_sweep(self):
        assert sweep_bars(_df(_base())).tolist() == [T]

    def test_close_through_the_pool_is_a_break_not_a_sweep(self):
        broke: Row = (99.5, 99.8, 99.0, 99.05)
        later_wick: Row = (99.5, 99.8, 99.1, 99.5)     # back under 99.2, above the new low
        rows = _lead() + [broke, FLAT, FLAT, later_wick, FLAT, FLAT]
        assert sweep_bars(_df(rows)).tolist() == []
        assert simulate(_df(rows)).trades.empty

    def test_a_spent_pool_is_not_swept_twice(self):
        again: Row = (100.5, 100.6, 99.05, 100.4)      # under 99.2 again, above the 99.0 wick
        assert sweep_bars(_df(_base(again, ABOVE, ABOVE))).tolist() == [T]

    def test_wick_inside_the_tolerance_is_not_a_sweep(self):
        shallow: Row = (99.5, 99.8, 99.15, 99.6)       # 0.05 under the pool, tolerance 0.065
        assert sweep_bars(_df(_lead() + [shallow, FLAT, FLAT])).tolist() == []

    def test_close_inside_the_band_leaves_the_pool_alive(self):
        in_band: Row = (99.5, 99.8, 99.0, 99.18)       # neither back above nor through
        swept: Row = (99.18, 99.8, 98.9, 99.6)
        assert sweep_bars(_df(_lead() + [in_band, swept, FLAT, FLAT])).tolist() == [T + 1]


class TestLinkToFvg:
    def test_impulse_two_bars_after_the_sweep_is_accepted(self):
        res = simulate(_df(_lead() + [SWEEP, FLAT, IMPULSE, C2, RETEST, RALLY]))
        assert len(res.trades) == 1
        t = res.trades.iloc[0]
        assert (t["trigger_i"], t["known_i"]) == (T, T + 3)
        assert (t["entry"], t["stop"]) == (100.0, 99.0)

    def test_impulse_three_bars_after_the_sweep_is_too_late(self):
        res = simulate(_df(_lead() + [SWEEP, FLAT, FLAT, IMPULSE, C2, RETEST, RALLY]))
        assert res.trades.empty
        assert res.funnel["no_zone"] == 1

    def test_gap_narrower_than_the_minimum_is_not_a_zone(self):
        thin_c2: Row = (100.8, 101.2, 99.83, 101.0)    # 0.03 gap against 0.1 ATR ~ 0.06
        res = simulate(_df(_lead() + [SWEEP, IMPULSE, thin_c2, RETEST, RALLY]))
        assert res.trades.empty

    def test_wick_taken_out_before_the_gap_confirms_voids_the_setup(self):
        deeper: Row = (99.6, 100.9, 98.95, 100.8)      # the impulse bar undercuts the sweep
        res = simulate(_df(_lead() + [SWEEP, deeper, C2, RETEST, RALLY]))
        assert res.trades.empty
        assert res.funnel["wick_broken"] == 1


class TestFill:
    def test_stop_on_the_fill_bar_is_a_loss(self):
        through: Row = (101.0, 101.1, 98.9, 100.5)
        t = simulate(_df(_base(through, RALLY))).trades.iloc[0]
        assert (t["entry_i"], t["exit_i"], t["exit_kind"]) == (T + 3, T + 3, "sl")
        assert t["exit"] == 99.0
        assert t["r"] == pytest.approx(-1.0 - (100 + 99) * 6e-4)

    def test_fill_bar_high_alone_is_not_a_take_profit(self):
        spike_then_fill: Row = (101.0, 102.5, 99.9, 101.0)
        res = simulate(_df(_base(spike_then_fill)))
        t = res.trades.iloc[0]
        assert not t["closed"] and t["exit_kind"] == "open"
        assert res.funnel["unfinished"] == 1

    def test_fill_bar_that_closes_beyond_the_target_is_a_take_profit(self):
        fill_then_run: Row = (101.0, 102.5, 99.9, 102.3)
        t = simulate(_df(_base(fill_then_run))).trades.iloc[0]
        assert (t["exit_kind"], t["exit"], t["exit_i"]) == ("tp", 102.0, T + 3)

    def test_stop_wins_a_bar_that_reaches_both(self):
        both: Row = (100.5, 102.5, 98.9, 100.0)
        t = simulate(_df(_base(RETEST, both))).trades.iloc[0]
        assert (t["exit_kind"], t["exit"]) == ("sl", 99.0)

    def test_open_through_the_limit_fills_at_the_open(self):
        gap_open: Row = (99.7, 100.4, 99.6, 100.2)
        t = simulate(_df(_base(gap_open, RALLY))).trades.iloc[0]
        assert t["entry"] == 99.7
        assert t["gross_r"] == pytest.approx((102.0 - 99.7) / (99.7 - 99.0))


class TestEntryVariants:
    def test_midpoint_entry_waits_for_the_middle_of_the_gap(self):
        res = simulate(_df(_base(RETEST, RALLY)), ComboParams(entry="ce"))
        t = res.trades.iloc[0]
        assert t["entry"] == pytest.approx(99.9)           # the gap is 99.8-100.0
        assert (t["stop"], t["tp"]) == (99.0, pytest.approx(101.7))

    def test_touch_of_the_edge_does_not_fill_a_midpoint_order(self):
        edge_only: Row = (101.0, 101.1, 99.95, 100.5)
        rows = _base(edge_only, RALLY)
        assert len(simulate(_df(rows), ComboParams(entry="near")).trades) == 1
        assert simulate(_df(rows), ComboParams(entry="ce")).trades.empty

    def test_fill_inside_the_new_york_window_is_taken(self):
        # The retest bar opens at 02:20 UTC on 5 January: 21:20 in New York.
        res = simulate(_df(_base(RETEST, RALLY)), ComboParams(fill_hours_ny=(21, 22)))
        assert len(res.trades) == 1

    def test_touch_outside_the_window_spends_the_zone(self):
        res = simulate(_df(_base(RETEST, RALLY, RETEST, RALLY)), ComboParams(fill_hours_ny=(10, 11)))
        assert res.trades.empty
        assert res.funnel["outside_window"] == 1


class TestGate:
    def test_setup_on_a_gated_bar_is_dropped(self):
        rows = _base(RETEST, RALLY)
        open_gate = np.ones(len(rows), bool)
        shut = open_gate.copy()
        shut[T + 2] = False                              # the bar the gap is known on
        assert len(simulate(_df(rows), gate=open_gate).trades) == 1
        res = simulate(_df(rows), gate=shut)
        assert res.trades.empty and res.funnel["gated"] == 1

    def test_higher_timeframe_break_is_released_at_its_candle_close(self):
        # A 4h candle opening at 04:00 breaks structure; it closes at 08:00.
        hourly = pd.date_range("2026-01-05 00:00", periods=12, freq="1h", tz="UTC", unit="ms")
        event = pd.DatetimeIndex([pd.Timestamp("2026-01-05 04:00", tz="UTC")])
        bias = release_bias(event, np.array([1], np.int8), 240, hourly, 60)
        # the 06:00 bar closes at 07:00, inside the candle; the 07:00 bar closes with it
        assert bias.tolist() == [0] * 7 + [1] * 5

    def test_no_events_is_no_bias(self):
        hourly = pd.date_range("2026-01-05 00:00", periods=3, freq="1h", tz="UTC", unit="ms")
        bias = release_bias(pd.DatetimeIndex([], tz="UTC"), np.empty(0, np.int8), 240, hourly, 60)
        assert bias.tolist() == [0, 0, 0]


class TestHigherTimeframeTarget:
    """The base setup (entry 100, stop 99) aimed at a 1h fractal high instead of
    2R. The hourly frame ends before the 5m frame starts unless a test says so."""

    P = ComboParams(target="htf_fractal")

    def _htf(self, highs: list[float], closes: dict[int, float] | None = None,
             start: str = "2026-01-04 18:00") -> tuple[pd.DataFrame, int, int]:
        closes = closes or {}
        rows = [(100.2, h, 100.0, closes.get(i, 100.2)) for i, h in enumerate(highs)]
        return _df(rows, freq="1h", start=start), 60, 5

    def test_target_is_the_nearest_fractal_above_the_entry(self):
        htf = self._htf([100.5, 101.5, 100.6, 103.0, 100.6, 100.5])
        res = simulate(_df(_base(RETEST, RALLY)), ComboParams(target="htf_fractal", min_rr=1.0), htf=htf)
        t = _only(res)
        assert (t["tp"], t["exit"], t["exit_kind"]) == (101.5, 101.5, "tp")
        assert t["gross_r"] == pytest.approx(1.5)

    def test_target_paying_less_than_the_floor_is_not_traded(self):
        htf = self._htf([100.5, 101.5, 100.6, 103.0, 100.6, 100.5])
        res = simulate(_df(_base(RETEST, RALLY)), self.P, htf=htf)       # 1.5R against 1.8
        assert res.trades.empty and res.funnel["rr_too_low"] == 1

    def test_far_fractal_is_taken_when_it_is_the_only_one(self):
        htf = self._htf([100.5, 100.6, 103.0, 100.6, 100.5, 100.4])
        t = _only(simulate(_df(_base(RETEST, RALLY)), self.P, htf=htf))
        assert t["tp"] == 103.0 and not t["closed"]          # 102.5 does not reach it

    def test_fractal_a_body_closed_above_is_no_longer_a_target(self):
        # The 22:00 candle closes at 101.8, above the 101.5 fractal.
        htf = self._htf([100.5, 101.5, 100.6, 103.0, 102.0, 100.5], closes={4: 101.8})
        t = _only(simulate(_df(_base(RETEST, RALLY)), self.P, htf=htf))
        assert t["tp"] == 103.0

    def test_wick_through_a_fractal_leaves_it_standing(self):
        htf = self._htf([100.5, 101.5, 100.6, 103.0, 102.0, 100.5])       # 22:00 high 102.0, close 100.2
        res = simulate(_df(_base(RETEST, RALLY)), ComboParams(target="htf_fractal", min_rr=1.0), htf=htf)
        assert _only(res)["tp"] == 101.5

    def test_fractal_not_yet_confirmed_when_the_setup_arises_is_not_a_target(self):
        # Pivot is the 01:00 candle; the 02:00 candle that confirms it closes at
        # 03:00, after the setup (known at 02:20) and the fill.
        htf = self._htf([100.5, 103.0, 100.6, 100.5], start="2026-01-05 00:00")
        res = simulate(_df(_base(RETEST, RALLY)), self.P, htf=htf)
        assert res.trades.empty and res.funnel["no_target"] == 1

    def test_no_fractal_above_the_entry_is_no_trade(self):
        htf = self._htf([99.0, 99.5, 99.1, 99.0])
        res = simulate(_df(_base(RETEST, RALLY)), self.P, htf=htf)
        assert res.trades.empty and res.funnel["no_target"] == 1

    def test_structural_target_without_the_frame_is_an_error(self):
        with pytest.raises(ValueError, match="higher-timeframe"):
            simulate(_df(_base(RETEST, RALLY)), self.P)


class TestOrderLife:
    def test_limit_fills_on_its_twentieth_bar(self):
        res = simulate(_df(_base(*[ABOVE] * 19, RETEST, RALLY)))
        assert len(res.trades) == 1
        assert res.trades.iloc[0]["entry_i"] == T + 3 + 19

    def test_limit_is_gone_on_its_twenty_first_bar(self):
        res = simulate(_df(_base(*[ABOVE] * 20, RETEST, RALLY)))
        assert res.trades.empty
        assert res.funnel["expired"] == 1

    def test_target_reached_without_a_retest_cancels_the_limit(self):
        ran: Row = (101.0, 102.5, 100.6, 102.0)
        res = simulate(_df(_base(ran, RETEST, RALLY)))
        assert res.trades.empty
        assert res.funnel["ran_away"] == 1

    def test_setup_during_an_open_position_is_skipped(self):
        hold: Row = (101.0, 101.2, 100.8, 101.0)
        pivot2: Row = (101.0, 101.2, 100.5, 101.0)
        sweep2: Row = (101.0, 101.1, 100.3, 101.0)
        impulse2: Row = (101.0, 101.7, 100.95, 101.6)
        c2_2: Row = (101.6, 101.8, 101.3, 101.7)
        rows = _base(RETEST, hold, hold, pivot2, hold, hold, hold, sweep2, impulse2, c2_2, hold)
        res = simulate(_df(rows))
        assert len(res.trades) == 1
        assert res.trades.iloc[0]["entry_i"] == T + 3
        assert res.funnel["setups"] == 2
        assert res.funnel["skipped_in_position"] == 1


class TestStopFloor:
    def test_floor_widens_a_stop_tighter_than_the_minimum(self):
        df = _df(_base(RETEST, RALLY))
        t = simulate(df, ComboParams(min_stop_atr=3.0)).trades.iloc[0]
        atr_at_c2 = 8.0 / 14            # the 14 true ranges ending at bar 27 sum to 8.0
        assert t["floor_hit"]
        assert t["stop"] == pytest.approx(100.0 - 3.0 * atr_at_c2)
        assert t["tp"] == pytest.approx(100.0 + 2.0 * 3.0 * atr_at_c2)
        assert not t["closed"]          # 102.5 no longer reaches the wider target

    def test_floor_leaves_a_wide_enough_stop_alone(self):
        t = simulate(_df(_base(RETEST, RALLY)), ComboParams(min_stop_atr=0.5)).trades.iloc[0]
        assert not t["floor_hit"] and t["stop"] == 99.0


class TestOtherPools:
    def _hourly(self, lows: dict[int, tuple[float, float]], n: int, start: str) -> pd.DataFrame:
        """Flat hourly bars at 100; `lows` maps bar -> (low, close)."""
        rows = []
        for i in range(n):
            lo, close = lows.get(i, (99.5, 100.0))
            rows.append((100.0, 100.5, lo, close))
        return _df(rows, freq="1h", start=start)

    def test_previous_day_low_is_swept_the_next_day_only(self):
        # Day 0 is the frame's first day and never a source. Day 1 low 95 (bar 30).
        # Day 2: bar 53 wicks to 94 and closes back -> sweep. Day 3: bar 80 wicks
        # to 94.5 — under day 1's low, but day 2's low (94) is the pool by then.
        df = self._hourly({30: (95.0, 100.0), 53: (94.0, 100.0), 80: (94.5, 100.0)},
                          n=96, start="2026-01-05 00:00")
        assert sweep_bars(df, ComboParams(pool="prev_day")).tolist() == [53]

    def test_first_day_of_the_frame_is_not_a_previous_day(self):
        df = self._hourly({5: (95.0, 100.0), 30: (94.0, 100.0)}, n=48, start="2026-01-05 00:00")
        assert sweep_bars(df, ComboParams(pool="prev_day")).tolist() == []

    def test_asia_low_is_swept_after_asia_closes(self):
        # Monday 2026-01-05 starts at bar 24; Kyiv is UTC+2 in January, so Asia
        # 02:00-10:00 Kyiv is 00:00-08:00 UTC: bars 24-31. Its low is set at bar 27.
        df = self._hourly({27: (96.0, 100.0), 36: (95.0, 100.0)}, n=48, start="2026-01-04 00:00")
        assert sweep_bars(df, ComboParams(pool="session")).tolist() == [36]

    def test_three_sessions_each_leave_a_pool_for_seven_days(self):
        # Monday 5 January, Kyiv = UTC+2. Bars are hours from Sunday 00:00 UTC:
        #   Asia     02-10 Kyiv = bars 24-31, low at bar 27
        #   London   10-18 Kyiv = bars 32-39, low at bar 34
        #   New York 15-23 Kyiv = bars 37-44, low at bar 42 (the sessions overlap)
        df = self._hourly({27: (96.0, 100.0), 34: (97.0, 100.0), 42: (98.0, 100.0)},
                          n=24 * 12, start="2026-01-04 00:00")
        pools = _session_pools(_bars(df), df.index)
        monday = [(lv, a, b) for lv, a, b in zip(pools.level, pools.live_from, pools.live_to) if a < 48]
        week = 7 * 24
        assert monday == [(96.0, 32, 32 + week), (97.0, 40, 40 + week), (98.0, 45, 45 + week)]

    def test_session_pool_is_cut_at_the_end_of_the_frame(self):
        df = self._hourly({27: (96.0, 100.0)}, n=72, start="2026-01-04 00:00")
        pools = _session_pools(_bars(df), df.index)
        assert pools.live_to.max() == 72

    def test_london_low_is_swept_in_the_new_york_afternoon(self):
        # Bar 43 is 19:00 UTC = 21:00 Kyiv: London has closed, New York is still
        # open. Only London's low (97) is a pool; the wick to 96.5 takes it.
        df = self._hourly({27: (97.0, 100.0), 34: (97.0, 100.0), 43: (96.5, 100.0)},
                          n=48, start="2026-01-04 00:00")
        assert sweep_bars(df, ComboParams(pool="session")).tolist() == [43]

    def test_weekend_has_no_session_pools(self):
        # Same shape one day earlier: bar 24 is Saturday 2026-01-03.
        df = self._hourly({27: (96.0, 100.0), 36: (95.0, 100.0)}, n=48, start="2026-01-02 00:00")
        assert sweep_bars(df, ComboParams(pool="session")).tolist() == []

    def test_session_hours_follow_kyiv_daylight_saving(self):
        # 07:00 UTC is 09:00 Kyiv in January (inside Asia, nothing to sweep yet)
        # and 10:00 Kyiv in July (Asia has closed, its low is a live pool).
        lows = {27: (96.0, 100.0), 31: (95.0, 100.0)}      # bar 31 is 07:00 UTC
        winter = self._hourly(lows, n=48, start="2026-01-04 00:00")    # Monday 5 Jan
        summer = self._hourly(lows, n=48, start="2026-07-05 00:00")    # Monday 6 Jul
        assert sweep_bars(winter, ComboParams(pool="session")).tolist() == []
        assert sweep_bars(summer, ComboParams(pool="session")).tolist() == [31]


def _random_walk(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.standard_t(3, n) * 0.25)
    open_ = np.concatenate(([100.0], close[:-1]))
    high = np.maximum(open_, close) + rng.exponential(0.2, n)
    low = np.minimum(open_, close) - rng.exponential(0.2, n)
    return _df(list(zip(open_, high, low, close)), freq="30min", start="2026-01-01 00:00")


class TestNoLookAhead:
    @pytest.mark.parametrize("pool", ["fractal", "prev_day", "session"])
    @pytest.mark.parametrize("side", ["long", "short"])
    def test_trades_closed_before_a_cut_do_not_depend_on_later_bars(self, pool, side):
        """Truncate the frame at N: every trade the full run closed before N must
        come out identical. Any stream that reads a bar before it closed, or a
        state that describes the end of the slice, breaks this."""
        df = _random_walk(30_000, seed=7)
        params = ComboParams(pool=pool, side=side)
        full = simulate(df, params).trades
        assert len(full[full["closed"]]) >= 10, "fixture must trade for the test to mean anything"
        for cut in (4_100, 9_700, 15_300, 22_600, 29_999):
            part = simulate(df.iloc[:cut], params).trades
            want = full[full["closed"] & (full["exit_i"] < cut)].reset_index(drop=True)
            got = part[part["closed"]].reset_index(drop=True)
            pd.testing.assert_frame_equal(got, want)


# ── The other chains ────────────────────────────────────────────────────────
#
# Fixture with a bearish gap overhead, for the IFVG and BPR chains:
#
#     bars 0-19   flat at 103
#     bar 20-22   drop: low[20] 102.0, high[22] 99.8 -> bearish gap 99.8-102.0
#     bar 25      low 99.2: fractal low, live from bar 28
#     bar 30      low 98.8, close 99.6: sweep

HIGH_FLAT: Row = (103.0, 103.3, 102.9, 103.0)
DROP = [(103.0, 103.3, 102.0, 102.2), (102.2, 102.3, 99.4, 99.5), (99.5, 99.8, 99.4, 99.5)]
DEEP_SWEEP: Row = (99.5, 99.8, 98.8, 99.6)
T2 = 30


def _gap_overhead(*tail: Row) -> list[Row]:
    return [HIGH_FLAT] * 20 + DROP + [FLAT] * 2 + [PIVOT] + [FLAT] * 4 + [DEEP_SWEEP, *tail]


def _flow(n: int, bias: int, events: list[tuple[int, int, int, bool]] = ()) -> FlowStreams:
    """Hand-made order flow: constant `bias`, events as (break, broken, direction, is_bos)."""
    cols = list(zip(*events)) if events else [(), (), (), ()]
    return FlowStreams(np.full(n, bias, np.int8), np.array(cols[0], np.int64),
                       np.array(cols[1], np.int64), np.array(cols[2], np.int8),
                       np.array(cols[3], bool))


def _only(res) -> pd.Series:
    assert len(res.trades) == 1, res.funnel
    return res.trades.iloc[0]


class TestSweepThenOrderBlock:
    """A2. In the base fixture bar 26 closes over the swing high at 99.8 (the
    flat highs tie, which a raw swing allows), and the lowest low of that leg is
    the sweep candle itself: it is the order block, 99.0-99.8."""

    def test_sweep_candle_confirmed_as_order_block_is_entered_at_its_top(self):
        retest: Row = (100.5, 100.6, 99.7, 100.2)
        t = _only(simulate(_df(_base(RETEST, retest, RALLY)), ComboParams(chain="A2")))
        assert (t["trigger_i"], t["known_i"], t["entry_i"]) == (T, T + 1, T + 4)
        assert (t["entry"], t["stop"]) == (99.8, 99.0)
        assert (t["exit_kind"], t["exit"]) == ("tp", pytest.approx(101.4))

    def test_a_lower_low_after_the_sweep_takes_the_order_block_away(self):
        lower: Row = (99.6, 99.7, 98.9, 99.5)          # not a sweep itself: no pool under it
        res = simulate(_df(_lead() + [SWEEP, lower, IMPULSE, C2, RETEST, RALLY]),
                       ComboParams(chain="A2"))
        assert res.trades.empty and res.funnel["sweeps"] == 1

    def test_break_later_than_the_link_window_is_not_linked(self):
        res = simulate(_df(_base(RETEST, RALLY)), ComboParams(chain="A2", link_bars=0))
        assert res.trades.empty and res.funnel["no_zone"] == 1


class TestSweepThenInversion:
    """A3. After the sweep a body closes above the bearish gap's top (102.0)."""

    UP: Row = (99.6, 101.0, 99.5, 100.9)
    PIERCE: Row = (100.9, 102.6, 100.8, 102.5)
    BACK: Row = (102.5, 102.7, 101.9, 102.3)
    RUN: Row = (102.3, 109.0, 102.2, 108.8)

    def test_gap_closed_through_after_the_sweep_is_entered_on_its_retest(self):
        rows = _gap_overhead(self.UP, self.PIERCE, self.BACK, self.RUN)
        t = _only(simulate(_df(rows), ComboParams(chain="A3")))
        assert (t["trigger_i"], t["known_i"], t["entry_i"]) == (T2, T2 + 2, T2 + 3)
        assert (t["entry"], t["stop"], t["tp"]) == (102.0, 98.8, pytest.approx(108.4))
        assert t["exit_kind"] == "tp"

    def test_wick_through_the_gap_is_not_an_inversion(self):
        wick_only: Row = (100.9, 102.6, 100.8, 101.9)
        still_under: Row = (101.9, 102.4, 101.5, 101.8)
        rows = _gap_overhead(self.UP, wick_only, still_under)
        res = simulate(_df(rows), ComboParams(chain="A3"))
        assert res.trades.empty and res.funnel["no_zone"] == 1

    def test_inversion_with_the_flow_puts_the_stop_behind_the_gap(self):
        rows = _gap_overhead(self.UP, self.PIERCE, self.BACK, self.RUN)
        t = _only(simulate(_df(rows), ComboParams(chain="C3"), _flow(len(rows), +1)))
        assert (t["known_i"], t["entry"], t["stop"]) == (T2 + 2, 102.0, 99.8)

    def test_inversion_against_the_flow_is_skipped(self):
        rows = _gap_overhead(self.UP, self.PIERCE, self.BACK)
        res = simulate(_df(rows), ComboParams(chain="C3"), _flow(len(rows), -1))
        assert res.trades.empty and res.funnel["against_flow"] == 1


class TestBpr:
    """A bullish gap 99.8-100.3 printed inside the live bearish gap 99.8-102.0."""

    UP: Row = (99.6, 101.0, 99.5, 100.9)
    C2_IN: Row = (100.9, 101.5, 100.3, 101.2)
    BACK: Row = (101.2, 101.3, 100.2, 100.8)

    def _rows(self) -> list[Row]:
        return _gap_overhead(self.UP, self.C2_IN, self.BACK)

    def test_sweep_then_overlapping_gaps_enters_at_the_top_of_the_shared_band(self):
        t = _only(simulate(_df(self._rows()), ComboParams(chain="A4")))
        assert (t["trigger_i"], t["known_i"], t["entry_i"]) == (T2, T2 + 2, T2 + 3)
        assert (t["entry"], t["stop"]) == (100.3, 98.8)

    def test_gap_with_nothing_overhead_is_not_a_bpr(self):
        res = simulate(_df(_base(RETEST, RALLY)), ComboParams(chain="A4"))
        assert res.trades.empty and res.funnel["no_zone"] == 1

    def test_bearish_gap_already_traded_through_is_dead(self):
        filled: Row = (99.5, 102.1, 99.4, 99.5)        # wicks to the bearish gap's far edge
        rows = [HIGH_FLAT] * 20 + DROP + [FLAT, filled] + [PIVOT] + [FLAT] * 4
        rows += [DEEP_SWEEP, self.UP, self.C2_IN, self.BACK]
        assert simulate(_df(rows), ComboParams(chain="A4")).trades.empty

    def test_bpr_with_the_flow_puts_the_stop_behind_the_gap(self):
        rows = self._rows()
        df = _df(rows)
        t = _only(simulate(df, ComboParams(chain="C4"), _flow(len(rows), +1)))
        floor = 100.3 - 0.5 * true_range_atr(df)[T2 + 2]
        assert t["entry"] == 100.3
        assert t["stop"] == pytest.approx(min(99.8, floor))


# No sweep here: 25 flat bars, then the impulse and the gap 99.8-100.0.
NO_SWEEP = [FLAT] * 25 + [IMPULSE, C2]
BRK = 25                 # the impulse bar: its body closes at 100.8


class TestGapAlone:
    def test_any_gap_is_traded_with_the_stop_under_its_two_candles(self):
        res = simulate(_df(NO_SWEEP + [RETEST, RALLY]), ComboParams(chain="C0"))
        t = _only(res)
        assert (t["known_i"], t["entry_i"]) == (BRK + 1, BRK + 2)
        assert (t["entry"], t["stop"], t["tp"]) == (100.0, 99.4, pytest.approx(101.2))
        assert t["exit_kind"] == "tp"

    def test_the_same_gap_is_not_a_sweep_setup(self):
        assert simulate(_df(NO_SWEEP + [RETEST, RALLY]), ComboParams(chain="A1")).trades.empty

    @pytest.mark.parametrize("bias, trades", [(+1, 1), (-1, 0), (0, 0)])
    def test_flow_filter_keeps_only_gaps_the_flow_agrees_with(self, bias, trades):
        rows = NO_SWEEP + [RETEST, RALLY]
        res = simulate(_df(rows), ComboParams(chain="C1"), _flow(len(rows), bias))
        assert len(res.trades) == trades

    def test_short_arm_wants_a_bearish_flow(self):
        rows = _mirror(NO_SWEEP + [RETEST, RALLY])
        short = ComboParams(chain="C1", side="short")
        assert len(simulate(_df(rows), short, _flow(len(rows), -1)).trades) == 1
        assert simulate(_df(rows), short, _flow(len(rows), +1)).trades.empty

    def test_flow_chain_without_flow_streams_is_an_error(self):
        with pytest.raises(ValueError, match="order-flow"):
            simulate(_df(NO_SWEEP), ComboParams(chain="C1"))


class TestBreakChains:
    """A hand-made event: the key printed at bar 21 is broken by bar 25's close."""

    def _flow(self, n: int, is_bos: bool, direction: int = +1) -> FlowStreams:
        return _flow(n, direction, [(BRK, 21, direction, is_bos)])

    @pytest.mark.parametrize("chain, is_bos", [("B1", True), ("B3", False)])
    def test_break_then_gap_in_the_leg(self, chain, is_bos):
        rows = NO_SWEEP + [RETEST, RALLY]
        t = _only(simulate(_df(rows), ComboParams(chain=chain), self._flow(len(rows), is_bos)))
        # the leg starts at the last of the equal lows before the break: bar 24
        assert (t["trigger_i"], t["known_i"]) == (BRK, BRK + 1)
        assert (t["entry"], t["stop"]) == (100.0, 99.4)

    @pytest.mark.parametrize("chain, is_bos", [("B1", False), ("B3", True)])
    def test_the_other_kind_of_break_is_not_this_chain(self, chain, is_bos):
        rows = NO_SWEEP + [RETEST, RALLY]
        assert simulate(_df(rows), ComboParams(chain=chain), self._flow(len(rows), is_bos)).trades.empty

    def test_break_against_the_arm_is_ignored(self):
        rows = NO_SWEEP + [RETEST, RALLY]
        res = simulate(_df(rows), ComboParams(chain="B1"), self._flow(len(rows), True, direction=-1))
        assert res.trades.empty

    def test_gap_retested_before_the_setup_exists_is_spent(self):
        # The gap confirms at bar 26 but the break only comes at bar 28, after
        # bar 27 has already traded back into it.
        rows = NO_SWEEP + [RETEST, ABOVE, RETEST, RALLY]
        flow = _flow(len(rows), +1, [(28, 21, +1, True)])
        res = simulate(_df(rows), ComboParams(chain="B1"), flow)
        assert res.trades.empty and res.funnel["zone_spent"] == 1

    @pytest.mark.parametrize("chain, is_bos", [("B2", True), ("B4", False)])
    def test_break_then_its_order_block(self, chain, is_bos):
        dip: Row = (100.8, 100.9, 99.7, 100.0)         # back into the 99.4-99.8 candle
        pop: Row = (100.0, 100.7, 99.9, 100.6)
        rows = [FLAT] * 25 + [IMPULSE, dip, pop]
        t = _only(simulate(_df(rows), ComboParams(chain=chain), self._flow(len(rows), is_bos)))
        assert (t["known_i"], t["entry_i"], t["exit_i"]) == (BRK, BRK + 1, BRK + 2)
        assert (t["entry"], t["stop"], t["exit"]) == (99.8, 99.4, pytest.approx(100.6))

    def test_order_block_left_behind_cancels_the_limit(self):
        res = simulate(_df(NO_SWEEP + [RETEST, RALLY]), ComboParams(chain="B2"),
                       self._flow(len(NO_SWEEP) + 2, True))
        assert res.trades.empty and res.funnel["ran_away"] == 1

    def test_sweep_then_break_then_gap(self):
        rows = _base(RETEST, RALLY)
        flow = _flow(len(rows), +1, [(T + 1, 22, +1, True)])
        t = _only(simulate(_df(rows), ComboParams(chain="A5"), flow))
        assert (t["trigger_i"], t["known_i"]) == (T, T + 2)
        assert (t["entry"], t["stop"]) == (100.0, 99.0)

    def test_sweep_with_no_break_in_the_link_window(self):
        rows = _base(RETEST, RALLY)
        res = simulate(_df(rows), ComboParams(chain="A5"), _flow(len(rows), +1))
        assert res.trades.empty and res.funnel["no_break"] == 1

    def test_order_block_with_the_flow(self):
        retest: Row = (100.5, 100.6, 99.7, 100.2)
        rows = _base(RETEST, retest, RALLY)
        t = _only(simulate(_df(rows), ComboParams(chain="C2"), _flow(len(rows), +1)))
        assert (t["known_i"], t["entry"], t["stop"]) == (T + 1, 99.8, 99.0)
        assert simulate(_df(rows), ComboParams(chain="C2"), _flow(len(rows), -1)).trades.empty


@pytest.fixture(scope="module")
def walk():
    df = _random_walk(30_000, seed=7)
    return df, flow_streams(df)


class TestEveryChainIsCausal:
    def test_flow_streams_only_append(self, walk):
        df, flow = walk
        for cut in (4_100, 15_300, 29_999):
            fresh, sliced = flow_streams(df.iloc[:cut]), flow.cut(cut)
            assert (fresh.bias == sliced.bias).all()
            for name in ("break_i", "broken_i", "direction", "is_bos"):
                assert getattr(fresh, name).tolist() == getattr(sliced, name).tolist()

    @pytest.mark.parametrize("chain", CHAINS)
    @pytest.mark.parametrize("side", ["long", "short"])
    def test_trades_closed_before_a_cut_do_not_depend_on_later_bars(self, walk, chain, side):
        df, flow = walk
        params = ComboParams(chain=chain, side=side)
        full = simulate(df, params, flow).trades
        assert len(full[full["closed"]]) >= 10, "fixture must trade for the test to mean anything"
        for cut in (4_100, 9_700, 15_300, 22_600, 29_999):
            part = simulate(df.iloc[:cut], params, flow_streams(df.iloc[:cut])).trades
            want = full[full["closed"] & (full["exit_i"] < cut)].reset_index(drop=True)
            got = part[part["closed"]].reset_index(drop=True)
            pd.testing.assert_frame_equal(got, want)

    @pytest.mark.parametrize("side", ["long", "short"])
    def test_higher_timeframe_target_does_not_depend_on_later_bars(self, walk, side):
        """The 4h frame is rebuilt from each cut frame, so its last candle is
        unfinished there — and must be invisible, both as a pivot's confirmation
        and as a break."""
        df, _ = walk

        def htf(frame: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
            agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
            return frame.resample("4h").agg(agg).dropna(), 240, 30

        params = ComboParams(side=side, target="htf_fractal")
        full = simulate(df, params, htf=htf(df)).trades
        assert len(full[full["closed"]]) >= 10, "fixture must trade for the test to mean anything"
        for cut in (4_100, 9_700, 15_300, 22_600, 29_999):
            part = simulate(df.iloc[:cut], params, htf=htf(df.iloc[:cut])).trades
            want = full[full["closed"] & (full["exit_i"] < cut)].reset_index(drop=True)
            got = part[part["closed"]].reset_index(drop=True)
            pd.testing.assert_frame_equal(got, want)
