"""ORB Algo port — the mechanics that decide its numbers, pinned on constructed bars.

The port as a whole was calibrated against the trader's TradingView screenshot
of 14 Sep 2026 (BTCUSDT.P 5m): 10009-10030 loaded bars reproduce the script's
own dashboard exactly — 35 days / 12 wins / 20 losses / 37.5% / 0.02% / 0.66%.
That check needs real market data, so it lives in `scripts/run_orb.py
calibrate`. These tests pin the individual behaviours instead, and in particular
the ones that make the published dashboard read better than the trades.
"""

from __future__ import annotations

import pandas as pd
import pytest

from copilot.backtest.orb_algo import (
    OrbParams,
    _pine_ema,
    _session_starts,
    dashboard,
    simulate,
)

Row = tuple[float, float, float, float]


def _df(rows: list[Row], start: str = "2026-01-01 23:50") -> pd.DataFrame:
    # unit="ms" on purpose: the data layer delivers datetime64[ms], and the first
    # port read those integers as nanoseconds — every opening range then lasted
    # 57 years and the strategy never traded.
    index = pd.date_range(start, periods=len(rows), freq="5min", tz="UTC",
                          name="ts", unit="ms")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)
    df["volume"] = 1.0
    return df


PRE = [(100.0, 100.2, 99.8, 100.0)] * 2           # 23:50, 23:55 — before the session
RANGE = [(100.0, 101.0, 99.0, 100.0)] * 6         # 00:00-00:25 -> range 101 / 99, centre 100
BREAKOUT = (100.0, 101.6, 100.0, 101.5)           # 00:30 closes above the range
RETEST = (101.5, 101.8, 100.8, 101.4)             # 00:35 wicks back in, closes out -> entry


def _entry_rows() -> list[Row]:
    return PRE + RANGE + [BREAKOUT, RETEST]


def _run_up_then_cross(drop_low: float) -> list[Row]:
    """Entry, a steady rally well past +0.2%, then one bar closing under the EMA."""
    rows = _entry_rows()
    close = 101.4
    for _ in range(12):
        prev, close = close, close + 0.6
        rows.append((prev, close + 0.1, close - 0.3, close))
    rows.append((close, close + 0.1, drop_low, close - 4.1))
    last = close - 4.1
    rows += [(last, last + 0.1, last - 0.1, last)] * 2
    return rows


def test_entry_needs_a_retest_and_the_stop_sits_at_the_range_centre():
    """Default sensitivity is Medium: one retest after the breakout bar."""
    rows = _entry_rows() + [(101.4, 101.5, 101.3, 101.4)] * 3
    t = simulate(_df(rows)).trades
    assert len(t) == 1, f"expected exactly one entry, got {len(t)}"
    trade = t.iloc[0]
    assert trade["side"] == "long"
    assert trade["entry_ts"] == pd.Timestamp("2026-01-02 00:35", tz="UTC"), (
        "entry must be the retest bar, not the breakout bar"
    )
    assert trade["entry"] == pytest.approx(101.4)
    assert trade["sl_init"] == pytest.approx(100.0), "Balanced stop is the centre of 101/99"


def test_a_close_back_inside_the_range_cancels_the_breakout():
    rows = PRE + RANGE + [BREAKOUT, (101.5, 101.6, 100.4, 100.5)]
    rows += [(100.5, 100.6, 100.4, 100.5)] * 3
    assert simulate(_df(rows)).trades.empty, "a failed breakout was traded"


def test_faithful_books_the_take_at_the_ema_the_bar_already_left():
    """The script's biggest flattering behaviour, measured on one trade.

    The trigger is the close crossing back under the EMA, so at the moment the
    exit is known price is BELOW the EMA — yet the fill is booked at the EMA.
    """
    df = _df(_run_up_then_cross(drop_low=104.3))
    tv = simulate(df, OrbParams()).orbs[0]
    honest = simulate(df, OrbParams(fill_at_close=True)).orbs[0]

    i = tv.tp_i[0]
    assert i is not None, "the fixture no longer reaches TP1"
    assert honest.tp_i[0] == i, "the trigger bar must not depend on the fill rule"

    ema = _pine_ema(((df["high"] + df["low"]) / 2).to_numpy(), 9)
    assert tv.tp_fill[0] == pytest.approx(ema[i])
    assert honest.tp_fill[0] == pytest.approx(df["close"].iloc[i])
    assert tv.tp_fill[0] - honest.tp_fill[0] > 1.0, (
        "for a long the EMA sits above the close that triggered the exit"
    )


def test_a_bar_that_hits_both_is_a_take_for_the_script_and_a_stop_honestly():
    """The drop bar wicks through the stop AND closes under the EMA.

    A resting stop fills intrabar, before any close-based exit can be decided,
    so the honest reading is the stop. The script skips the stop on TP bars.
    """
    df = _df(_run_up_then_cross(drop_low=99.5))
    tv = simulate(df, OrbParams()).orbs[0]
    honest = simulate(df, OrbParams(stop_first=True)).orbs[0]

    assert tv.tp_fill[0] is not None and tv.exit_kind is None, (
        "the script should have booked TP1 and kept the position"
    )
    assert honest.exit_kind == "sl" and honest.tp_fill == [None, None, None]


def test_the_dashboard_books_a_profitable_session_exit_as_a_loss():
    """`diffPercent` takes abs(), and the session exit is subtracted as a loss.

    Price sits 0.2% above entry all day — just short of the script's minimum
    take — and the next session flattens the trade in profit. The trade makes
    money; the dashboard counts a loss.
    """
    flat = (101.6, 101.7, 101.5, 101.6)
    rows = _entry_rows() + [flat] * 280 + [flat]   # to 23:55, then next day's 00:00
    res = simulate(_df(rows))

    trade = res.trades.iloc[0]
    assert trade["exit_kind"] == "session"
    assert trade["gross_pct"] == pytest.approx((101.6 - 101.4) / 101.4 * 100)

    d = dashboard(res)
    assert (d["wins"], d["losses"]) == (0, 1)
    assert d["total_profit_pct"] == pytest.approx(-0.2, abs=0.005)


def test_the_new_york_anchor_follows_daylight_saving():
    """09:30 New York is 14:30 UTC in winter and 13:30 UTC from 8 March 2026.

    A TradingView custom session typed in UTC would not move, and would open the
    range an hour away from the real NYSE open for half the year.
    """
    index = pd.date_range("2026-03-06", "2026-03-10", freq="5min", tz="UTC",
                          inclusive="left", unit="ms")
    starts = index[_session_starts(index, "ny_open")]
    assert [f"{t:%m-%d %H:%M}" for t in starts] == [
        "03-06 14:30", "03-07 14:30", "03-08 13:30", "03-09 13:30",
    ]


def test_utc_anchor_opens_at_midnight():
    """What `session.isfirstbar_regular` gives on Binance crypto symbols — the
    trader's chart draws the range from 03:00 Kyiv, i.e. 00:00 UTC."""
    index = pd.date_range("2026-01-01 23:50", periods=10, freq="5min", tz="UTC", unit="ms")
    starts = index[_session_starts(index, "utc0")]
    assert [f"{t:%m-%d %H:%M}" for t in starts] == ["01-02 00:00"]


# ---------------------------------------------------------------------------
# The trader's variant (2026-09-15): fractal stop, stop floor, fixed R, HTF bias
# ---------------------------------------------------------------------------

import numpy as np  # noqa: E402

from copilot.backtest.orb_algo import bias_series  # noqa: E402

PRE_FRACTAL = [
    (100.0, 100.2, 99.8, 100.0),   # 23:30
    (100.0, 100.1, 99.3, 99.9),    # 23:35  fractal low 99.3, confirmed by 23:40
    (99.9, 100.2, 99.6, 100.0),    # 23:40
    (100.0, 100.2, 99.8, 100.0),   # 23:45
    (100.0, 100.2, 99.8, 100.0),   # 23:50
    (100.0, 100.2, 99.8, 100.0),   # 23:55
]
# 00:10 prints a fractal low INSIDE the range, after the open — nearer in time
# than 23:35, and exactly the one the rule must ignore.
RANGE_WITH_INNER_FRACTAL = (
    [(100.0, 101.0, 99.0, 100.0)] * 2
    + [(100.0, 101.0, 98.9, 100.0)]
    + [(100.0, 101.0, 99.0, 100.0)] * 3
)


def _fractal_rows(after: list[Row]) -> list[Row]:
    return PRE_FRACTAL + RANGE_WITH_INNER_FRACTAL + [BREAKOUT, RETEST] + after


def test_fractal_stop_is_the_last_fractal_confirmed_before_the_open():
    rows = _fractal_rows([(101.4, 101.5, 101.3, 101.4)] * 3)
    t = simulate(_df(rows, start="2026-01-01 23:30"), OrbParams(sl_method="Fractal")).trades
    assert len(t) == 1
    assert t.iloc[0]["sl_init"] == pytest.approx(99.3), (
        "the stop must sit at the 23:35 fractal; 00:10 printed after the open"
    )


def test_a_fractal_stop_closer_than_the_floor_is_widened():
    rows = _fractal_rows([(101.4, 101.5, 101.3, 101.4)] * 3)
    params = OrbParams(sl_method="Fractal", min_stop_atr=10.0)
    trade = simulate(_df(rows, start="2026-01-01 23:30"), params).trades.iloc[0]
    assert trade["entry"] - trade["sl_init"] > 101.4 - 99.3, "the floor did not widen the stop"
    assert trade["sl_init"] == pytest.approx(trade["entry"] - 10.0 * trade["entry_atr"])


def test_fixed_r_takes_the_whole_position_at_one_and_a_half_r():
    """Entry 101.4, fractal stop 99.3: risk 2.1, target 104.55."""
    rows = _fractal_rows([
        (101.4, 102.5, 101.3, 102.4),
        (102.4, 103.8, 102.3, 103.7),
        (103.7, 104.6, 103.6, 104.5),     # high 104.6 reaches 104.55
    ])
    params = OrbParams(sl_method="Fractal", tp_method="FixedR", tp_r=1.5)
    trade = simulate(_df(rows, start="2026-01-01 23:30"), params).trades.iloc[0]
    assert trade["exit_kind"] == "tp" and trade["closed"]
    assert trade["gross_pct"] == pytest.approx(1.5 * 2.1 / 101.4 * 100)
    assert trade["r"] == pytest.approx(1.5)


def test_bias_skips_the_breakout_against_it_and_keeps_the_session_open():
    rows = PRE + RANGE + [
        (100.0, 100.0, 98.4, 98.5),   # 00:30 breaks DOWN
        (98.5, 99.2, 98.3, 98.6),     # 00:35 retest -> a short, against the bias
        (98.6, 100.0, 98.5, 100.0),   # 00:40 back inside the range
        BREAKOUT,                     # 00:45 breaks UP
        RETEST,                       # 00:50 retest -> a long, with the bias
    ] + [(101.4, 101.5, 101.3, 101.4)] * 3
    df = _df(rows)
    free = simulate(df).trades
    biased = simulate(df, bias=np.ones(len(df), dtype=np.int8)).trades
    assert list(free["side"]) == ["short"], "without a bias the first breakout is the trade"
    assert list(biased["side"]) == ["long"]
    assert biased.iloc[0]["entry_ts"] == pd.Timestamp("2026-01-02 00:50", tz="UTC")


def test_htf_bias_is_released_only_when_the_breaking_candle_closes():
    """A 1h candle opening 10:00 breaks structure; its close is 11:00.

    The 5m bars closing at 10:50 and 10:55 are inside that hour and must not
    see the break. Releasing it at break_ts would be look-ahead.
    """
    events = [{"break_ts": "2026-01-02T10:00:00Z", "direction": "bullish"}]
    index = pd.date_range("2026-01-02 10:45", periods=4, freq="5min", tz="UTC", unit="ms")
    assert list(bias_series(events, htf_minutes=60, index=index)) == [0, 0, 1, 1]
