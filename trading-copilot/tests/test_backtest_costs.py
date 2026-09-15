"""Costs are not a rounding term when the stop is structural.

`SetupRule.fee_bps` and `slippage_bps` default to 0.0 and no rule file sets
them, so a research run that forgets to pass them scores free trades. That is
the same class of mistake as the one the June 2026 audit blamed for every
earlier "edge" (one-sided fees + look-ahead), and it bites hardest exactly
where 30mOF lives: `sl_logic="of_key"` pins the stop to a structural level, so
a fill deep inside a POI can leave a stop of a fraction of an ATR, and
`_finalize_trade` charges cost in R as (entry + exit) * bps / risk_distance —
inversely proportional to that stop.

These tests pin the arithmetic so the effect stays visible in the suite rather
than being rediscovered from a suspicious 69R arm.
"""

from __future__ import annotations

import pytest

from copilot.backtest.engine import _finalize_trade
from copilot.backtest.rules_30mof import STAGE1_RULES
from copilot.journal.record import TradeRecord


def _trade(entry: float, sl: float) -> TradeRecord:
    return TradeRecord(
        symbol="BTCUSDT",
        direction="long",
        entry_price=entry,
        sl_price=sl,
        setup_name="test",
    )


def _cost_in_r(entry: float, sl: float, exit_price: float) -> float:
    free = _finalize_trade(
        _trade(entry, sl), "win", exit_price, None, fee_bps=0.0, slippage_bps=0.0
    ).pnl_r
    charged = _finalize_trade(
        _trade(entry, sl), "win", exit_price, None, fee_bps=4.0, slippage_bps=2.0
    ).pnl_r
    return free - charged


def test_cost_in_r_scales_inversely_with_the_stop():
    """Halving the stop doubles what the round trip costs in R."""
    wide = _cost_in_r(64000.0, 63600.0, 64720.0)    # 400-point stop
    tight = _cost_in_r(64000.0, 63800.0, 64360.0)   # 200-point stop
    assert tight > wide
    assert tight == round(wide * 2, 4) or abs(tight - wide * 2) < 0.01, (
        f"expected the tighter stop to cost about twice as much R: {wide} vs {tight}"
    )


def test_a_micro_stop_pays_multiple_r_per_round_trip():
    """A ~0.1 ATR stop on BTC is not a cheap trade, it is a ruinous one.

    `_sl_from_of_key` falls back to a 0.1 ATR buffer beyond the flow's counter
    key, so an entry sitting on that key leaves a stop of tens of dollars. At
    that size the fee alone is worth several R, which is what turns an arm's
    expectancy from spectacular into negative.
    """
    cost = _cost_in_r(64000.0, 63975.0, 65600.0)    # 25-point stop
    assert cost > 3.0, (
        f"a 25-point stop at BTC 64k should cost >3R per round trip, got {cost}"
    )


def test_setup_rules_ship_without_costs_so_runners_must_supply_them():
    """A guard on the default, not an endorsement of it.

    If someone later sets fees inside `rules_30mof.py`, `scripts/run_30mof.py`
    would double-charge them via `dataclasses.replace`. This test fails then,
    which is the moment to pick one place and delete the other.
    """
    rule = STAGE1_RULES["of30_market_long"]
    assert rule.fee_bps == 0.0 and rule.slippage_bps == 0.0, (
        "rules_30mof now sets costs itself — remove the override in "
        "scripts/run_30mof.py or the sweep charges them twice"
    )


# ---------------------------------------------------------------------------
# The fix: a floor on the structural stop (trader's decision, 2026-08-27)
# ---------------------------------------------------------------------------

import pandas as pd  # noqa: E402

from copilot.backtest.rules_30mof import STAGE1_RULES as _S1  # noqa: E402
from copilot.backtest.simulate import _compute_atr, resolve_sl  # noqa: E402


def _df(n: int = 60, price: float = 64000.0) -> pd.DataFrame:
    """Bars with a ~$200 true range, so ATR is a round number to reason about."""
    index = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC", name="ts")
    rows = [(price, price + 100.0, price - 100.0, price)] * n
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)
    df["volume"] = 1000.0
    return df[["open", "high", "low", "close", "volume"]]


def _cache(key_low: float) -> dict:
    return {"detect_order_flow": {"key_low": {"price": key_low}}}


def test_a_stop_on_top_of_the_key_is_widened_to_the_floor():
    """The $0.90 stop of run 1, prevented.

    `of_key` puts the stop just under the flow's counter key. When the POI the
    entry filled at sits on that key, the two are the same price.
    """
    df = _df()
    atr = _compute_atr(df)
    entry = 64000.0
    sl = resolve_sl("of_key", entry, "long", df, _cache(63999.5), min_stop_atr=0.5)
    assert abs(entry - sl) == pytest.approx(atr * 0.5), (
        f"stop should have been widened to 0.5 ATR ({atr * 0.5}), got {abs(entry - sl)}"
    )
    assert sl < entry, "a long's stop must stay below the entry after widening"


def test_a_healthy_structural_stop_is_left_alone():
    """The floor is a floor, not a replacement — market entries keep their level."""
    df = _df()
    entry = 64000.0
    sl = resolve_sl("of_key", entry, "long", df, _cache(63400.0), min_stop_atr=0.5)
    assert sl < 63400.0, "the structural level was overwritten instead of respected"
    assert abs(entry - sl) > _compute_atr(df) * 0.5


def test_the_floor_mirrors_for_shorts():
    df = _df()
    atr = _compute_atr(df)
    entry = 64000.0
    cache = {"detect_order_flow": {"key_high": {"price": 64000.5}}}
    sl = resolve_sl("of_key", entry, "short", df, cache, min_stop_atr=0.5)
    assert sl > entry, "a short's stop must sit above the entry"
    assert abs(entry - sl) == pytest.approx(atr * 0.5)


def test_30mof_ships_with_the_floor_on():
    """Run 1's POI arms were produced without it and are not comparable."""
    assert _S1["of30_poi_long"].min_stop_atr == 0.5
    assert _S1["of30_market_long"].min_stop_atr == 0.5
