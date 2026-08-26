"""
Tests for the rule-DSL extensions the 1h3m Bellissimo setup needs.

Each one exists because a piece of the trader's methodology could not be
written down before it:
  * value_ref            — "3m BOS is above the raid" (two moving values)
  * same_day             — "only a fractal of the current day counts"
  * invalidation_conditions — "if the reaction went the other way first, skip"
  * fta_or_skip / fta_or_liquidity — what to do when the first obstacle is close
  * detect_previous_day_levels     — PDH/PDL as a quality-of-liquidity criterion
"""

import pandas as pd
import pytest

from copilot.backtest.rules import (
    Condition,
    RuleConfigError,
    SetupRule,
    evaluate_conditions_on_slice,
)
from copilot.backtest.simulate import _FRACTAL_TARGET_POOL, resolve_tp
from copilot.detectors.prev_day import detect_previous_day_levels


def _flat_df(n: int = 10, freq: str = "1h") -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    df = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0},
        index=idx,
    )
    df.index.name = "ts"
    return df


class TestValueRef:
    """A condition compares one detector's field against another's."""

    def _registry(self, bos_level: float):
        return {"detect_bos": lambda d, **k: {"events": [{"broken_level": bos_level}]}}

    def _cond(self):
        return Condition(
            "detect_bos", "events.0.broken_level", "gt",
            value_ref="signal:detect_liquidity.recent_sweeps.0.swept_level",
        )

    def test_bos_above_the_raid_passes(self):
        signal = {"detect_liquidity": {"recent_sweeps": [{"swept_level": 100.0}]}}
        ok, _ = evaluate_conditions_on_slice(
            [self._cond()], _flat_df(), self._registry(105.0), ref_cache=signal
        )
        assert ok is True

    def test_bos_below_the_raid_fails(self):
        signal = {"detect_liquidity": {"recent_sweeps": [{"swept_level": 110.0}]}}
        ok, _ = evaluate_conditions_on_slice(
            [self._cond()], _flat_df(), self._registry(105.0), ref_cache=signal
        )
        assert ok is False

    def test_missing_reference_fails_closed(self):
        """No signal cache → the comparison is unanswerable, so the setup is not taken."""
        ok, _ = evaluate_conditions_on_slice(
            [self._cond()], _flat_df(), self._registry(105.0)
        )
        assert ok is False

    def test_self_namespace_reads_the_same_slice(self):
        registry = {
            "detect_bos": lambda d, **k: {"events": [{"broken_level": 105.0}]},
            "detect_market_structure": lambda d, **k: {"last_swing_high": {"price": 103.0}},
        }
        cond = Condition(
            "detect_bos", "events.0.broken_level", "gt",
            value_ref="self:detect_market_structure.last_swing_high.price",
        )
        ok, _ = evaluate_conditions_on_slice([cond], _flat_df(), registry)
        assert ok is True

    def test_unknown_namespace_is_rejected_at_construction(self):
        with pytest.raises(RuleConfigError):
            Condition("d", "f", "gt", value_ref="htf:other.field")

    def test_value_ref_survives_serialisation(self):
        cond = self._cond()
        assert Condition.from_dict(cond.to_dict()).value_ref == cond.value_ref


class TestSameDayOperator:
    def _eval(self, pool_ts: str, op: str, n_bars: int = 10):
        registry = {
            "detect_liquidity": lambda d, **k: {
                "recent_sweeps": [{"swept_level": 100.0, "pool_ts": pool_ts}]
            }
        }
        cond = Condition("detect_liquidity", "recent_sweeps.0.pool_ts", op)
        # Last bar of a 10-bar 1h frame starting 2026-01-01 00:00 → 09:00 same day
        return evaluate_conditions_on_slice([cond], _flat_df(n_bars), registry)[0]

    def test_pool_from_today_passes(self):
        assert self._eval("2026-01-01T02:00:00Z", "same_day") is True

    def test_pool_from_yesterday_fails(self):
        assert self._eval("2025-12-31T22:00:00Z", "same_day") is False

    def test_not_same_day_inverts(self):
        assert self._eval("2025-12-31T22:00:00Z", "not_same_day") is True
        assert self._eval("2026-01-01T02:00:00Z", "not_same_day") is False

    def test_missing_timestamp_fails_closed(self):
        registry = {"detect_liquidity": lambda d, **k: {"recent_sweeps": []}}
        cond = Condition("detect_liquidity", "recent_sweeps.0.pool_ts", "same_day")
        assert evaluate_conditions_on_slice([cond], _flat_df(), registry)[0] is False


class TestSweepCarriesPoolAge:
    """`same_day` needs something to point at — the pool's own formation time."""

    def test_sweep_record_reports_when_the_pool_formed(self):
        from copilot.detectors.liquidity import detect_liquidity

        rows = []
        for price in [100, 101, 100.5, 102, 101, 100.8, 102, 101.2, 100.9]:
            rows.append(
                {"open": price - 0.2, "high": price + 0.3, "low": price - 0.4,
                 "close": price, "volume": 1000.0}
            )
        rows.append({"open": 101, "high": 103.5, "low": 100.8, "close": 101.2, "volume": 1500.0})
        for price in [100.5, 100.2, 99.8]:
            rows.append({"open": price, "high": price + 0.2, "low": price - 0.3,
                         "close": price, "volume": 900.0})

        idx = pd.date_range("2026-01-01", periods=len(rows), freq="1h", tz="UTC")
        df = pd.DataFrame(rows, index=idx).astype("float64")
        df.index.name = "ts"

        sweeps = detect_liquidity(df, swing_lookback=1)["recent_sweeps"]
        assert sweeps, "fixture must produce at least one sweep"
        for sweep in sweeps:
            assert "pool_ts" in sweep and "pool_age_bars" in sweep
            assert sweep["pool_age_bars"] >= 0
            assert pd.Timestamp(sweep["pool_ts"]) <= pd.Timestamp(sweep["sweep_ts"]), (
                "a pool cannot form after the sweep that takes it"
            )


class TestFtaTakeProfit:
    """Entry 100, SL 98 → risk 2. A bearish FVG 104–106 sits in the way,
    with a liquidity pool at 112 behind it."""

    CACHE = {
        "detect_fvg": {
            "fvgs": [{"type": "bearish", "upper": 106.0, "lower": 104.0,
                      "fill_state": "untouched"}]
        },
        "detect_liquidity": {"buyside_liquidity": [{"price": 112.0}]},
    }

    def _tp(self, logic: str, min_rr: float, cache=None):
        return resolve_tp(
            logic, 100.0, 98.0, "long", _flat_df(), dict(cache or self.CACHE),
            min_rr=min_rr,
        )

    def test_tp_lands_on_the_near_edge_of_the_obstacle(self):
        """104, not 106: targeting the far side assumes the zone gets eaten."""
        assert self._tp("fta_or_skip", 1.8) == 104.0

    def test_fta_too_close_skips_the_trade(self):
        assert self._tp("fta_or_skip", 3.0) is None

    def test_fta_too_close_trades_through_in_the_other_variant(self):
        assert self._tp("fta_or_liquidity", 3.0) == 112.0

    def test_clear_path_targets_liquidity(self):
        cache = {"detect_liquidity": self.CACHE["detect_liquidity"]}
        assert self._tp("fta_or_skip", 1.8, cache) == 112.0

    def test_mitigated_zones_are_not_obstacles(self):
        cache = {
            "detect_fvg": {"fvgs": [{"type": "bearish", "upper": 106.0, "lower": 104.0,
                                     "fill_state": "filled"}]},
            "detect_liquidity": self.CACHE["detect_liquidity"],
        }
        assert self._tp("fta_or_skip", 1.8, cache) == 112.0

    def test_same_direction_zones_are_not_obstacles(self):
        """A bullish FVG above a long is support on the way, not trouble."""
        cache = {
            "detect_fvg": {"fvgs": [{"type": "bullish", "upper": 106.0, "lower": 104.0,
                                     "fill_state": "untouched"}]},
            "detect_liquidity": self.CACHE["detect_liquidity"],
        }
        assert self._tp("fta_or_skip", 1.8, cache) == 112.0

    def test_short_side_mirrors(self):
        cache = {
            "detect_order_block": {"obs": [{"type": "bullish", "high": 96.0, "low": 94.0}]},
            "detect_liquidity": {"sellside_liquidity": [{"price": 88.0}]},
        }
        tp = resolve_tp("fta_or_skip", 100.0, 102.0, "short", _flat_df(), cache, min_rr=1.8)
        assert tp == 96.0, "near edge for a short is the TOP of the zone below"


class TestInvalidationConditions:
    def test_rule_carries_and_serialises_them(self):
        rule = SetupRule(
            name="r", direction="long",
            conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
            entry_after="signal_close", sl_logic="swing", tp_logic="rr:2.0",
            invalidation_conditions=[
                Condition("detect_bos", "events.0.direction", "eq", "bearish")
            ],
        )
        restored = SetupRule.from_dict(rule.to_dict())
        assert len(restored.invalidation_conditions) == 1
        assert restored.invalidation_conditions[0].value == "bearish"

    def test_counter_bos_abandons_the_signal(self):
        """The setup died while we waited: the entry that comes later is not
        the trade the rule describes."""
        from copilot.backtest.engine import BacktestEngine

        n_htf, n_ltf = 80, 80 * 12
        htf = _flat_df(n_htf)
        ltf = _flat_df(n_ltf, freq="5min")

        class _Src:
            def get_ohlc(self, symbol, tf, bars, start_time=None, end_time=None):
                return htf if tf == "1h" else ltf

        base = dict(
            name="inv", direction="long",
            conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
            entry_after="signal_close", sl_logic="pct:2.0", tp_logic="rr:2.0",
            min_rr=1.0, entry_tf="5m", entry_after_ltf="signal_close",
            max_entry_wait_bars_ltf=200, required_session=None,
        )
        registry = {
            "detect_fvg": lambda d, **k: {"count_active": 0},
            "detect_bos": lambda d, **k: {"events": [{"direction": "bearish"}]},
        }
        engine = BacktestEngine(source=_Src(), detector_registry=registry)

        without = engine.run("BTCUSDT", "1h", SetupRule(**base), bars=n_htf, write_journal=False)
        with_inv = engine.run(
            "BTCUSDT", "1h",
            SetupRule(**base, invalidation_conditions=[
                Condition("detect_bos", "events.0.direction", "eq", "bearish")
            ]),
            bars=n_htf, write_journal=False,
        )

        assert without.total_trades > 0, "fixture must trade without the invalidation"
        assert with_inv.total_trades == 0, "counter-BOS must abandon every signal"
        assert with_inv.skipped_entry >= without.skipped_entry


class TestPreviousDayLevels:
    def _two_days(self) -> pd.DataFrame:
        idx = pd.date_range("2026-01-01", periods=48, freq="1h", tz="UTC")
        highs = [101.0] * 24 + [103.0] * 24
        lows = [99.0] * 24 + [98.0] * 24
        highs[5] = 110.0    # day 1 high
        lows[7] = 90.0      # day 1 low
        df = pd.DataFrame(
            {"open": 100.0, "high": highs, "low": lows, "close": 100.0, "volume": 1000.0},
            index=idx,
        ).astype("float64")
        df.index.name = "ts"
        return df

    def test_reports_the_previous_completed_day(self):
        result = detect_previous_day_levels(self._two_days())
        assert result["prev_day"] == "2026-01-01"
        assert result["pdh"] == 110.0
        assert result["pdl"] == 90.0

    def test_today_is_never_used_as_the_previous_day(self):
        """The day in progress has no final extremes — using them is a leak."""
        df = self._two_days()
        df.iloc[30, df.columns.get_loc("high")] = 200.0   # spike on day 2
        assert detect_previous_day_levels(df)["pdh"] == 110.0

    def test_sweep_and_break_are_distinguished(self):
        df = self._two_days()
        df.iloc[30, df.columns.get_loc("high")] = 111.0   # wick above PDH, closes at 100
        result = detect_previous_day_levels(df)
        assert result["pdh_swept"] is True
        assert result["pdh_broken"] is False

        df.iloc[30, df.columns.get_loc("close")] = 112.0  # now closes through
        broken = detect_previous_day_levels(df)
        assert broken["pdh_broken"] is True
        assert broken["pdh_swept"] is False

    def test_day_boundary_is_a_parameter_not_an_assumption(self):
        """UTC midnight and New York midnight are 5 hours apart, so the same
        bar can belong to yesterday under one convention and not the other."""
        df = self._two_days()
        # 02:00 UTC on Jan 1 = 21:00 EST on Dec 31: inside UTC's "previous day"
        # (Jan 1), outside New York's (which runs 05:00 Jan 1 → 05:00 Jan 2).
        df.iloc[2, df.columns.get_loc("high")] = 150.0

        utc = detect_previous_day_levels(df, day_tz="UTC")
        ny = detect_previous_day_levels(df, day_tz="America/New_York")

        assert utc["day_tz"] == "UTC" and ny["day_tz"] == "America/New_York"
        assert utc["pdh"] == 150.0
        assert ny["pdh"] == 110.0, "the spike belongs to a different day in NY time"

    def test_single_day_is_insufficient(self):
        one_day = self._two_days().iloc[:24]
        assert detect_previous_day_levels(one_day)["status"] == "insufficient_data"


class TestWeeklyTimeframe:
    """The 1W HTF filter of the 1h3m setup needs a timeframe the stack did not
    know about — it was absent from every lookup table at once."""

    def test_weekly_is_valid_everywhere_it_must_be(self):
        from copilot.backtest.engine import _TF_MINUTES
        from copilot.data.base import VALID_TIMEFRAMES
        from copilot.data.binance import _TF_MAP
        from copilot.data.cache import _DEFAULT_TTL

        assert "1w" in VALID_TIMEFRAMES
        assert _TF_MAP["1w"] == "1w"
        assert _DEFAULT_TTL["1w"] > 0
        assert _TF_MINUTES["1w"] == 7 * 24 * 60

    def test_assert_valid_tf_accepts_weekly(self):
        from copilot.data.base import assert_valid_tf

        assert_valid_tf("1w")   # must not raise


class TestBellissimoRules:
    """The assembled setup — a review surface for the trader, and a guard that
    the encoding does not drift from docs/SETUP_1H3M_BELLISSIMO.md."""

    def _rules(self):
        from copilot.backtest.rules_bellissimo import BELLISSIMO_RULES

        return BELLISSIMO_RULES

    def _flat(self, conditions):
        from copilot.backtest.rules import AnyOf

        for cond in conditions:
            if isinstance(cond, AnyOf):
                yield from cond.conditions
            else:
                yield cond

    def test_four_arms_two_sides_by_two_fta_policies(self):
        assert set(self._rules()) == {
            "bellissimo_1h3m_long", "bellissimo_1h3m_short",
            "bellissimo_1h3m_long_softfta", "bellissimo_1h3m_short_softfta",
        }

    def test_fta_policy_is_the_only_difference_between_paired_arms(self):
        """The soft arms must be the strict arms with one field changed —
        otherwise the A/B measures more than the FTA rule."""
        rules = self._rules()
        for side in ("long", "short"):
            strict = rules[f"bellissimo_1h3m_{side}"].to_dict()
            soft = rules[f"bellissimo_1h3m_{side}_softfta"].to_dict()
            differing = {
                k for k in strict
                if strict[k] != soft.get(k)
            }
            assert differing == {"name", "tp_logic"}, (
                f"{side} arms differ in {differing - {'name', 'tp_logic'}} "
                "beyond the FTA policy"
            )

    def test_no_htf_gate_at_all(self):
        """1D, then 1W, then the 1H context itself were all dropped: each
        deleted trades rather than describing them. Reinstate the 1H context
        only if counter-trend entries prove to stop out often."""
        for rule in self._rules().values():
            assert rule.htf_conditions == []
            assert not any(
                c.detector == "detect_market_structure" for c in self._flat(rule.conditions)
            )

    def test_the_only_hourly_trigger_is_a_sweep(self):
        long_rule = self._rules()["bellissimo_1h3m_long"]
        short_rule = self._rules()["bellissimo_1h3m_short"]

        def sweep_side(rule):
            return next(
                c.value for c in self._flat(rule.conditions)
                if c.field == "recent_sweeps.0.side"
            )

        # Direction is set by the sweep: lows taken → long, highs taken → short.
        assert sweep_side(long_rule) == "sellside"
        assert sweep_side(short_rule) == "buyside"

    def test_swept_pool_may_be_of_any_age(self):
        """Requiring a same-day pool was a coding error, not the methodology."""
        for rule in self._rules().values():
            assert not any(
                c.op in ("same_day", "not_same_day") for c in self._flat(rule.conditions)
            )

    def test_entry_is_a_bos_against_the_sweep(self):
        rules = self._rules()
        assert next(
            c.value for c in rules["bellissimo_1h3m_long"].entry_conditions
            if c.field == "events.0.direction"
        ) == "bullish"
        assert next(
            c.value for c in rules["bellissimo_1h3m_short"].entry_conditions
            if c.field == "events.0.direction"
        ) == "bearish"

    def test_invalidation_is_continuation_in_the_sweep_direction(self):
        rules = self._rules()
        assert rules["bellissimo_1h3m_long"].invalidation_conditions[0].value == "bearish"
        assert rules["bellissimo_1h3m_short"].invalidation_conditions[0].value == "bullish"

    def test_bos_must_sit_beyond_the_raid(self):
        rules = self._rules()
        for name, op in (("bellissimo_1h3m_long", "gt"), ("bellissimo_1h3m_short", "lt")):
            cond = next(
                c for c in rules[name].entry_conditions if c.field == "events.0.broken_level"
            )
            assert cond.op == op
            assert cond.value_ref == "signal:detect_liquidity.recent_sweeps.0.swept_level"

    def test_entry_fractals_are_three_candle(self):
        """Always 3-candle on 3M — and swing_lookback counts bars EACH SIDE, so
        3-candle is 1. Passing 3 would silently ask for a 7-candle pivot."""
        for rule in self._rules().values():
            for cond in list(self._flat(rule.entry_conditions)) \
                    + list(self._flat(rule.invalidation_conditions)):
                assert cond.kwargs.get("swing_lookback") == 1, (
                    f"{rule.name}: {cond.field} is not a 3-candle fractal"
                )

    def test_liquidity_pools_are_five_candle_fractals(self):
        for rule in self._rules().values():
            for cond in self._flat(rule.conditions):
                if cond.detector == "detect_liquidity":
                    assert cond.kwargs.get("swing_lookback") == 2

    def test_pool_quality_criteria_are_alternatives(self):
        from copilot.backtest.rules import AnyOf

        for rule in self._rules().values():
            groups = [c for c in rule.conditions if isinstance(c, AnyOf)]
            assert len(groups) == 1
            fields = {c.field for c in groups[0].conditions}
            assert any(f.endswith("touches") for f in fields)
            assert any(f.endswith("type") for f in fields)
            assert fields & {"pdh_swept", "pdl_swept"}

    def test_stop_sits_behind_the_sweeping_fractal(self):
        for rule in self._rules().values():
            assert rule.sl_logic == "sweep_fractal", (
                "an hourly swing stop inflates risk past the 1.8R floor"
            )

    def test_target_is_the_fractal_or_fta_rule(self):
        """Both FTA policies are the same target rule; they differ only in
        whether an FTA too close to pay min_rr vetoes the trade."""
        for name, rule in self._rules().items():
            expected = (
                "fractal_or_fta_soft" if name.endswith("_softfta") else "fractal_or_fta"
            )
            assert rule.tp_logic == expected, f"{name} has tp_logic={rule.tp_logic}"

    def test_trading_window_is_nine_to_twentythree_kyiv(self):
        """The trader's reference trade fired at 21:00 Kyiv — the note's
        09:00-17:00 window would have rejected it."""
        for rule in self._rules().values():
            assert rule.required_hours_kyiv == (9, 23)
            assert rule.required_session is None

    def test_research_frame_is_applied_to_every_arm(self):
        for rule in self._rules().values():
            assert rule.min_rr == 1.8
            assert rule.risk_pct == 1.0
            assert rule.tp_levels == []
            assert rule.sl_after_tp1 is None


class TestKyivHourWindow:
    """The session labels tile the day in fixed blocks (ny_pm 17-20, off_hours
    20-02), so 09:00-23:00 cannot be written as a list of them."""

    def _rule(self, hours):
        from copilot.backtest.rules import Condition, SetupRule

        return SetupRule(
            name="win", direction="long",
            conditions=[Condition("detect_fvg", "count_active", "gte", 0)],
            entry_after="signal_close", sl_logic="pct:2.0", tp_logic="rr:2.0",
            min_rr=1.0, required_hours_kyiv=hours,
            # Close each trade after one bar so the engine returns to IDLE and
            # keeps sampling — a flat fixture otherwise yields a single trade
            # that never resolves, and every window looks identical.
            max_bars_open=1,
        )

    def _run(self, hours):
        import numpy as np
        import pandas as pd

        from copilot.backtest.engine import BacktestEngine

        n = 400
        idx = pd.date_range("2026-03-02", periods=n, freq="1h", tz="UTC")
        df = pd.DataFrame(
            {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0,
             "volume": np.full(n, 1000.0)},
            index=idx,
        ).astype("float64")
        df.index.name = "ts"

        class _Src:
            def get_ohlc(self, symbol, tf, bars, start_time=None, end_time=None):
                return df

        engine = BacktestEngine(
            source=_Src(), detector_registry={"detect_fvg": lambda d, **k: {"count_active": 0}}
        )
        summary = engine.run("BTCUSDT", "1h", self._rule(hours), bars=n, write_journal=False)
        return summary, df

    def test_signals_land_only_inside_the_window(self):
        import pandas as pd

        summary, _ = self._run((9, 23))
        assert summary.total_trades > 0
        for trade in summary.trades:
            hour = pd.Timestamp(trade.ts_entry).tz_convert("Europe/Kyiv").hour
            assert 9 <= hour < 23, f"entry at {hour}:00 Kyiv is outside 09-23"

    def test_a_narrower_window_takes_strictly_fewer(self):
        wide, _ = self._run((9, 23))
        narrow, _ = self._run((9, 17))
        assert narrow.total_signals < wide.total_signals

    def test_window_crossing_midnight_is_supported(self):
        import pandas as pd

        summary, _ = self._run((22, 3))
        assert summary.total_trades > 0
        for trade in summary.trades:
            hour = pd.Timestamp(trade.ts_entry).tz_convert("Europe/Kyiv").hour
            assert hour >= 22 or hour < 3


class TestSweepFractalStop:
    def test_stop_sits_at_the_sweep_bar_extreme(self):
        import pandas as pd

        from copilot.backtest.simulate import resolve_sl

        idx = pd.date_range("2026-01-01", periods=6, freq="1h", tz="UTC")
        lows = [99.0, 98.0, 95.0, 98.5, 99.0, 99.2]
        df = pd.DataFrame(
            {"open": 100.0, "high": 101.0, "low": lows, "close": 100.0, "volume": 1000.0},
            index=idx,
        ).astype("float64")
        df.index.name = "ts"

        cache = {
            "detect_liquidity": {
                "recent_sweeps": [
                    {"side": "sellside", "swept_level": 96.0,
                     "sweep_ts": "2026-01-01 02:00:00+00:00"}
                ]
            },
            "detect_market_structure": {"atr_14": 1.0},
        }
        sl = resolve_sl("sweep_fractal", 100.0, "long", df, cache)
        # The 02:00 bar took the liquidity; its low is 95.0, minus a small buffer.
        assert 94.5 < sl < 95.0

    def test_falls_back_to_the_swept_level_when_the_bar_is_gone(self):
        import pandas as pd

        from copilot.backtest.simulate import resolve_sl

        idx = pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC")
        df = pd.DataFrame(
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0},
            index=idx,
        ).astype("float64")
        df.index.name = "ts"
        cache = {
            "detect_liquidity": {
                "recent_sweeps": [{"side": "sellside", "swept_level": 96.0, "sweep_ts": "nonsense"}]
            },
            "detect_market_structure": {"atr_14": 1.0},
        }
        assert 95.5 < resolve_sl("sweep_fractal", 100.0, "long", df, cache) < 96.0


class TestFractalOrFtaTarget:
    """Entry 100, SL 98 → risk 2, so the 1.8R floor is 103.6.

    Targets are the two nearest 3-candle fractals on the signal timeframe; an
    FTA in front of one replaces it at its near edge, whatever R that pays.
    """

    def _df(self):
        import pandas as pd

        idx = pd.date_range("2026-01-01", periods=5, freq="1h", tz="UTC")
        df = pd.DataFrame(
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0},
            index=idx,
        ).astype("float64")
        df.index.name = "ts"
        return df

    def _fractals(self, *prices):
        return {
            f"detect_fractals_3_{_FRACTAL_TARGET_POOL}": {
                "fractals": [{"price": p, "is_broken": False} for p in prices]
            }
        }

    def _fvg(self, lower, upper):
        return {
            "detect_fvg": {
                "fvgs": [{"type": "bearish", "upper": upper, "lower": lower,
                          "fill_state": "untouched"}]
            }
        }

    def _tp(self, cache):
        from copilot.backtest.simulate import resolve_tp

        return resolve_tp(
            "fractal_or_fta", 100.0, 98.0, "long", self._df(), dict(cache), min_rr=1.8
        )

    def test_first_fractal_taken_when_it_pays(self):
        assert self._tp(self._fractals(105.0, 110.0)) == 105.0

    def test_second_fractal_used_when_the_first_is_too_close(self):
        assert self._tp(self._fractals(102.0, 110.0)) == 110.0

    def test_search_stops_at_the_second_fractal(self):
        """Three candidates, only the third pays — the trader looks no further."""
        assert self._tp(self._fractals(101.0, 102.0, 110.0)) is None

    def test_obstacle_before_the_first_target_replaces_it(self):
        cache = {**self._fractals(105.0, 110.0), **self._fvg(104.0, 104.5)}
        assert self._tp(cache) == 104.0, "take the near edge, not a capped 1.8R"

    def test_obstacle_paying_more_than_the_floor_keeps_its_own_r(self):
        """FTA at 106 = 3.0R — the near edge is the target, not 103.6."""
        cache = {**self._fractals(110.0, 115.0), **self._fvg(106.0, 108.0)}
        assert self._tp(cache) == 106.0

    def test_obstacle_closer_than_the_floor_skips_the_trade(self):
        cache = {**self._fractals(105.0, 110.0), **self._fvg(102.0, 103.0)}
        assert self._tp(cache) is None

    def test_obstacle_between_first_and_second_fractal(self):
        cache = {**self._fractals(102.0, 110.0), **self._fvg(106.0, 109.0)}
        assert self._tp(cache) == 106.0

    def test_no_reachable_target_skips(self):
        assert self._tp(self._fractals(101.0, 102.0)) is None

    def test_broken_fractals_are_not_targets(self):
        cache = {
            f"detect_fractals_3_{_FRACTAL_TARGET_POOL}": {
                "fractals": [
                    {"price": 105.0, "is_broken": True},
                    {"price": 106.0, "is_broken": False},
                ]
            }
        }
        assert self._tp(cache) == 106.0

    def test_short_side_mirrors(self):
        from copilot.backtest.simulate import resolve_tp

        cache = {
            f"detect_fractals_3_{_FRACTAL_TARGET_POOL}": {
                "fractals": [{"price": 95.0, "is_broken": False},
                             {"price": 90.0, "is_broken": False}]
            }
        }
        assert resolve_tp(
            "fractal_or_fta", 100.0, 102.0, "short", self._df(), cache, min_rr=1.8
        ) == 95.0

    def test_target_fractals_are_three_candle_on_the_signal_timeframe(self):
        """5-candle is the detector default; this rule must ask for 3."""
        calls = []

        def fake_fractals(df, **kwargs):
            calls.append(kwargs)
            return {"fractals": [{"price": 105.0, "is_broken": False}]}

        from copilot.backtest.simulate import resolve_tp

        resolve_tp(
            "fractal_or_fta", 100.0, 98.0, "long", self._df(), {},
            min_rr=1.8, registry={"detect_fractals": fake_fractals},
        )
        assert calls and calls[0].get("bars") == "3"


class TestBellissimoWaitWindow:
    def test_entry_wait_is_one_hour(self):
        from copilot.backtest.rules_bellissimo import BELLISSIMO_RULES

        for rule in BELLISSIMO_RULES.values():
            assert rule.entry_tf == "3m"
            assert rule.max_entry_wait_bars_ltf == 20, "20 × 3m = 1 hour"


class TestFtaPolicies:
    """Strict vs soft FTA — the 1-Aug reference trade decides between them.

    Reconstructed from the real numbers of that setup (BTCUSDT futures,
    1 Aug 2026, entry 62562.6 / stop 62347.5 → risk 215.1):
      - a clean 3-candle fractal target at 63126.6 → 2.62R
      - an FVG near edge at 62596.5, 34 points above entry → 0.16R
    The strict reading lets the 0.16R obstacle veto the 2.62R target, so the
    trade the trader actually took never happens.
    """

    ENTRY = 62562.6
    SL = 62347.5
    FRACTAL = 63126.6
    NEAR_FTA = 62596.5

    def _resolve(self, tp_logic, fta_level):
        from copilot.backtest.simulate import resolve_tp

        registry = {
            "detect_fractals": lambda df, **kw: {
                "fractals": [
                    {"type": "swing_high", "price": self.FRACTAL, "is_broken": False},
                ]
            },
            "detect_fvg": lambda df, **kw: {
                "fvgs": [
                    {"type": "bearish", "upper": fta_level + 50.0,
                     "lower": fta_level, "is_mitigated": False},
                ]
            },
        }
        return resolve_tp(
            tp_logic, self.ENTRY, self.SL, "long",
            slice_df=None, detector_cache={}, min_rr=1.8, registry=registry,
        )

    def test_strict_policy_lets_a_trivial_fta_veto_the_trade(self):
        assert self._resolve("fractal_or_fta", self.NEAR_FTA) is None

    def test_soft_policy_reproduces_the_1_aug_reference_trade(self):
        tp = self._resolve("fractal_or_fta_soft", self.NEAR_FTA)
        assert tp == self.FRACTAL, (
            f"soft policy returned {tp}, expected the 2.62R fractal at {self.FRACTAL} "
            "— the trade the trader actually took on 1 Aug"
        )
        rr = (tp - self.ENTRY) / (self.ENTRY - self.SL)
        assert round(rr, 2) == 2.62

    def test_soft_policy_still_honours_an_fta_that_pays(self):
        """A real obstacle beyond min_rr still pulls the target nearer."""
        far_fta = 62980.0                      # ~1.94R — a genuine wall
        tp = self._resolve("fractal_or_fta_soft", far_fta)
        assert tp == far_fta, (
            "an FTA that pays min_rr must still replace the further fractal"
        )

    def test_policies_agree_when_no_fta_is_in_the_way(self):
        strict = self._resolve("fractal_or_fta", 99999.0)
        soft = self._resolve("fractal_or_fta_soft", 99999.0)
        assert strict == soft == self.FRACTAL


class TestFractalTargetPool:
    """The target rule wants the nearest fractals in PRICE; the detector's
    default returns the most recent in TIME. Mixing the two silently changed
    27% of target resolutions on the run-2 window."""

    def test_target_search_asks_for_more_than_the_detector_default(self):
        from copilot.backtest.simulate import _FRACTAL_TARGET_POOL, _tp_fractal_or_fta

        seen: list[dict] = []

        def spy(df, **kw):
            seen.append(kw)
            return {"fractals": []}

        _tp_fractal_or_fta(100.0, 99.0, "long", None, {}, {"detect_fractals": spy}, 1.8)
        assert seen, "detect_fractals was never called"
        assert seen[0].get("max_results") == _FRACTAL_TARGET_POOL
        assert _FRACTAL_TARGET_POOL > 10, "10 is the truncating default we are avoiding"

    def test_an_older_but_nearer_fractal_is_not_missed(self):
        """With the truncating default this level was invisible and the rule
        reached past it."""
        from copilot.backtest.simulate import _tp_fractal_or_fta

        registry = {
            "detect_fractals": lambda df, **kw: {
                "fractals": [
                    {"type": "swing_high", "price": 130.0, "is_broken": False},
                    {"type": "swing_high", "price": 102.0, "is_broken": False},
                ]
            },
            "detect_fvg": lambda df, **kw: {"fvgs": []},
        }
        # entry 100, stop 99 → risk 1; 102 pays 2R, 130 pays 30R.
        tp = _tp_fractal_or_fta(100.0, 99.0, "long", None, {}, registry, 1.8)
        assert tp == 102.0, "the nearer target must win regardless of its age"

    def test_cache_key_is_tied_to_the_pool_size(self):
        """A cache entry built from 10 fractals must not answer a 60-fractal
        question — that is how the truncation would sneak back in."""
        from copilot.backtest.simulate import _FRACTAL_TARGET_POOL, _tp_fractal_or_fta

        calls = {"n": 0}

        def counting(df, **kw):
            calls["n"] += 1
            return {"fractals": []}

        cache = {"detect_fractals_3": {"fractals": [{"type": "swing_high",
                                                     "price": 999.0,
                                                     "is_broken": False}]}}
        tp = _tp_fractal_or_fta(100.0, 99.0, "long", None, cache,
                                {"detect_fractals": counting, "detect_fvg":
                                 lambda df, **kw: {"fvgs": []}}, 1.8)
        assert calls["n"] == 1, "the stale 10-fractal cache entry was reused"
        assert tp is None
        assert f"detect_fractals_3_{_FRACTAL_TARGET_POOL}" in cache
