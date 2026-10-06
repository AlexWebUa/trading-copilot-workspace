"""Dukascopy source — the calendar is the part that can be silently wrong.

Spot gold's day starts at 17:00 New York (21:00 UTC in summer, 22:00 in winter),
the market shuts for an hour there and for the weekend, and 4h / daily bars are
anchored to that moment. Every test builds its own minutes; nothing is downloaded.
"""

from __future__ import annotations

import pandas as pd
import pytest

from copilot.data.cache import BatchedOHLCStore
from copilot.data.dukascopy import (
    DukascopySource, csv_to_frame, resample, source_id, trading_day,
)


def _minutes(start: str, end: str, skip: list[tuple[str, str]] = ()) -> pd.DataFrame:
    """One bar per minute in [start, end) UTC, price = minutes since `start`,
    except inside the `skip` windows (the market is shut there)."""
    index = pd.date_range(start, end, freq="1min", tz="UTC", inclusive="left", name="ts", unit="ms")
    keep = pd.Series(True, index=index)
    for a, b in skip:
        keep[(index >= pd.Timestamp(a, tz="UTC")) & (index < pd.Timestamp(b, tz="UTC"))] = False
    index = index[keep.to_numpy()]
    price = ((index - pd.Timestamp(start, tz="UTC")) / pd.Timedelta(minutes=1)).to_numpy(float)
    return pd.DataFrame({"open": price, "high": price + 0.5, "low": price - 0.5,
                         "close": price, "volume": 1.0}, index=index)


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


class TestTradingDay:
    def test_summer_session_starts_at_21_utc(self):
        # Tuesday 7 July 2026, New York is UTC-4: 17:00 there is 21:00 UTC.
        index = pd.DatetimeIndex([_ts("2026-07-07 20:59"), _ts("2026-07-07 22:00")])
        assert trading_day(index).strftime("%Y-%m-%d").tolist() == ["2026-07-07", "2026-07-08"]

    def test_winter_session_starts_at_22_utc(self):
        # Tuesday 13 January 2026, New York is UTC-5: 17:00 there is 22:00 UTC.
        index = pd.DatetimeIndex([_ts("2026-01-13 21:59"), _ts("2026-01-13 23:00")])
        assert trading_day(index).strftime("%Y-%m-%d").tolist() == ["2026-01-13", "2026-01-14"]

    def test_sunday_evening_is_monday(self):
        index = pd.DatetimeIndex([_ts("2026-07-05 22:00")])          # Sunday 18:00 New York
        assert trading_day(index).strftime("%A").tolist() == ["Monday"]


class TestResample:
    def test_hourly_bars_sit_on_the_utc_clock(self):
        df = _minutes("2026-07-07 10:00", "2026-07-07 12:00")
        out = resample(df, "1h")
        assert out.index.tolist() == [_ts("2026-07-07 10:00"), _ts("2026-07-07 11:00")]
        first = out.iloc[0]
        assert (first["open"], first["close"], first["high"], first["low"]) == (0.0, 59.0, 59.5, -0.5)
        assert first["volume"] == 60.0

    def test_four_hour_bars_count_from_17_new_york_in_summer(self):
        # Monday 21:00 UTC to Tuesday 21:00 UTC, with the break 21:00-22:00.
        df = _minutes("2026-07-06 21:00", "2026-07-07 21:00",
                      skip=[("2026-07-06 21:00", "2026-07-06 22:00")])
        out = resample(df, "4h")
        assert out.index.strftime("%H:%M").tolist() == ["21:00", "01:00", "05:00", "09:00", "13:00", "17:00"]
        assert out["volume"].tolist() == [180.0, 240.0, 240.0, 240.0, 240.0, 240.0]

    def test_four_hour_bars_move_an_hour_in_winter(self):
        df = _minutes("2026-01-12 23:00", "2026-01-13 22:00")
        out = resample(df, "4h")
        assert out.index.strftime("%H:%M").tolist() == ["22:00", "02:00", "06:00", "10:00", "14:00", "18:00"]

    def test_daily_bar_is_one_session_not_one_utc_day(self):
        # Two sessions: Mon 22:00 -> Tue 21:00 and Tue 22:00 -> Wed 21:00 (UTC, summer).
        df = _minutes("2026-07-06 22:00", "2026-07-08 21:00",
                      skip=[("2026-07-07 21:00", "2026-07-07 22:00")])
        out = resample(df, "1d")
        assert out.index.tolist() == [_ts("2026-07-06 21:00"), _ts("2026-07-07 21:00")]
        assert out["volume"].tolist() == [23 * 60.0, 23 * 60.0]
        # the second session opens with the first minute after the break
        assert out.iloc[1]["open"] == 24 * 60.0

    def test_weekend_leaves_no_bars_and_monday_starts_on_sunday_evening(self):
        df = _minutes("2026-07-03 12:00", "2026-07-06 02:00",
                      skip=[("2026-07-03 21:00", "2026-07-05 22:00")])
        out = resample(df, "4h")
        assert out.index.tolist() == [_ts("2026-07-03 09:00"), _ts("2026-07-03 13:00"),
                                      _ts("2026-07-03 17:00"), _ts("2026-07-05 21:00"),
                                      _ts("2026-07-06 01:00")]

    def test_early_close_leaves_a_short_bar(self):
        df = _minutes("2026-07-07 18:00", "2026-07-07 18:28")
        out = resample(df, "1h")
        assert len(out) == 1 and out.iloc[0]["volume"] == 28.0

    def test_weekly_bar_starts_on_sunday_evening(self):
        df = _minutes("2026-07-05 22:00", "2026-07-10 21:00")
        out = resample(df, "1w")
        assert out.index.tolist() == [_ts("2026-07-05 21:00")]

    def test_one_minute_is_returned_as_is(self):
        df = _minutes("2026-07-07 10:00", "2026-07-07 10:05")
        assert resample(df, "1m") is df


class TestCsv:
    def test_millisecond_timestamps_become_a_utc_index(self, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("timestamp,open,high,low,close,volume\n"
                        "1788739200000,4422.915,4424.985,4421.975,4423.135,18060\n"
                        "1788739260000,4423.095,4426.285,4423.095,4426.245,12240\n", encoding="utf-8")
        df = csv_to_frame(path)
        assert df.index.tolist() == [_ts("2026-09-07 00:00"), _ts("2026-09-07 00:01")]
        assert df.index.name == "ts"
        assert df.iloc[0].tolist() == [4422.915, 4424.985, 4421.975, 4423.135, 18060.0]

    def test_empty_file_is_an_empty_frame(self, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("timestamp,open,high,low,close,volume\n", encoding="utf-8")
        assert csv_to_frame(path).empty


class TestSource:
    @pytest.fixture
    def source(self, tmp_path) -> DukascopySource:
        store = BatchedOHLCStore(cache_dir=tmp_path)
        bid = _minutes("2026-07-06 22:00", "2026-07-07 21:00")
        ask = bid.copy()
        ask[["open", "high", "low", "close"]] += 0.6
        store.save(source_id("bid"), "XAUUSD", "1m", bid, at_history_start=True)
        store.save(source_id("ask"), "XAUUSD", "1m", ask, at_history_start=True)
        return DukascopySource(store)

    def test_supports_only_what_was_downloaded(self, source):
        assert source.supports("xauusd")
        assert not source.supports("EURUSD")

    def test_missing_history_says_how_to_get_it(self, source):
        with pytest.raises(FileNotFoundError, match="fetch_dukascopy"):
            source.history("EURUSD", "1h")

    def test_get_ohlc_returns_the_last_bars_of_the_bid_frame(self, source):
        out = source.get_ohlc("XAUUSD", "1h", bars=3)
        assert out.index.tolist() == [_ts("2026-07-07 18:00"), _ts("2026-07-07 19:00"),
                                      _ts("2026-07-07 20:00")]
        assert list(out.columns) == ["open", "high", "low", "close", "volume"]

    def test_ask_frame_carries_the_spread(self, source):
        bid = source.history("XAUUSD", "15m")
        ask = source.history("XAUUSD", "15m", side="ask")
        assert bid.index.equals(ask.index)
        assert (ask["close"] - bid["close"]).round(9).unique().tolist() == [0.6]

    def test_history_window_is_cut_on_minutes(self, source):
        out = source.history("XAUUSD", "1h", start=_ts("2026-07-07 10:30"), end=_ts("2026-07-07 12:00"))
        assert out.index.tolist() == [_ts("2026-07-07 10:00"), _ts("2026-07-07 11:00")]
        assert out.iloc[0]["volume"] == 30.0          # only the minutes from 10:30 on
