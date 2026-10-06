"""
Dukascopy history, read offline — the first non-crypto instrument (XAUUSD spot).

`scripts/fetch_dukascopy.py` downloads M1 bars once and stores them through
`BatchedOHLCStore`; this module only reads. No request is ever made from here,
so a backtest on gold runs without a network.

What differs from the Binance frames, and matters to everything downstream:

  The market closes.  Spot gold trades Sunday 17:00 to Friday 17:00 New York
      with a daily break at 17:00-18:00, and closes early around holidays. The
      frame simply has no bars there. Nothing may assume a fixed number of bars
      per day, and a "gap" in the index is the calendar, not missing data.
  The day starts at 17:00 New York.  That is 21:00 or 22:00 UTC depending on
      daylight saving. `trading_day` is the session a bar belongs to; a
      previous-day high taken on UTC midnight would cut every session in two.
  4h and daily bars are anchored to that same moment, as broker charts draw
      them. Bars of an hour or less sit on the UTC clock, which coincides with
      the New York one at every whole hour.
  Two prices.  The canonical frame is BID — what a spot chart shows, so the
      wicks are the ones a trader sees. ASK is kept alongside so a cost model
      can charge the spread actually quoted on each bar.
  It is one bank's feed.  Not an exchange tape: another broker's wicks differ
      by a few cents to a few tenths of a dollar, and COMEX futures carry a
      basis on top. `volume` is Dukascopy's own tick volume — kept so the
      canonical five columns hold, never to be read as market volume.
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from copilot.data.base import TF_MINUTES, assert_valid_tf
from copilot.data.cache import BatchedOHLCStore
from copilot.data.normalize import OHLCV_COLUMNS, make_empty

SIDES = ("bid", "ask")
_NY = ZoneInfo("America/New_York")
_SESSION_START = pd.Timedelta(hours=17)       # New York wall clock
_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def source_id(side: str) -> str:
    """Cache namespace of one price side. Bid is the default frame."""
    if side not in SIDES:
        raise ValueError(f"side {side!r}")
    return "dukascopy" if side == "bid" else "dukascopy_ask"


def csv_to_frame(path: Path) -> pd.DataFrame:
    """One `dukascopy-node` CSV (timestamp in ms, OHLC, volume) as a canonical frame."""
    raw = pd.read_csv(path)
    if raw.empty:
        return make_empty()
    df = raw[OHLCV_COLUMNS].astype("float64")
    df.index = pd.DatetimeIndex(pd.to_datetime(raw["timestamp"], unit="ms", utc=True), name="ts")
    return df


def _wall(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """New York wall-clock time, naive. Arithmetic on it is safe inside a trading
    week: the clocks change at 02:00 on a Sunday, when the market is shut."""
    return index.tz_convert(_NY).tz_localize(None)


def trading_day(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The session each bar belongs to, as a naive date: bars from 17:00 New York
    onward belong to the NEXT calendar day, so Sunday evening is Monday."""
    return (_wall(index) + (pd.Timedelta(hours=24) - _SESSION_START)).normalize()


def resample(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Aggregate M1 bars to `tf`. A bucket exists if it holds at least one bar:
    the hour before an early close is a short bar, the daily break is no bar.

    Up to 1h the buckets sit on the UTC clock. Above that they are counted from
    the session start, 17:00 New York, so a 4h bar never straddles the daily
    break and a daily bar is one whole session — a UTC-midnight day would glue
    the end of one session to the start of the next.
    """
    assert_valid_tf(tf)
    minutes = TF_MINUTES[tf]
    if minutes == 1 or df.empty:
        return df
    if minutes <= 60:
        key = df.index.floor(f"{minutes}min")
    else:
        wall = _wall(df.index)
        start = (wall - _SESSION_START).normalize() + _SESSION_START
        if tf == "1w":
            start = start - pd.to_timedelta((start.dayofweek + 1) % 7, unit="D")   # back to Sunday
            bucket = start
        else:
            step = pd.Timedelta(minutes=minutes)
            bucket = start + ((wall - start) // step) * step
        key = bucket.tz_localize(_NY, ambiguous=True, nonexistent="shift_forward").tz_convert("UTC")
    out = df.groupby(key).agg(_AGG)
    out.index = pd.DatetimeIndex(out.index, name="ts").as_unit(df.index.unit)
    return out[OHLCV_COLUMNS]


class DukascopySource:
    """`DataSource` over the stored M1 frames. Offline by construction."""

    source_id = "dukascopy"

    def __init__(self, store: BatchedOHLCStore | None = None):
        self._store = store or BatchedOHLCStore()
        self._m1: dict[tuple[str, str], pd.DataFrame] = {}

    def _minutes(self, symbol: str, side: str) -> pd.DataFrame:
        key = (symbol.upper(), side)
        if key not in self._m1:
            loaded = self._store.load(source_id(side), key[0], "1m")
            if loaded is None:
                raise FileNotFoundError(
                    f"no Dukascopy {side} history for {key[0]}: run "
                    f"scripts/fetch_dukascopy.py --instrument {key[0].lower()}")
            self._m1[key] = loaded[0]
        return self._m1[key]

    def supports(self, symbol: str) -> bool:
        return self._store.load(source_id("bid"), symbol.upper(), "1m") is not None

    def history(self, symbol: str, tf: str, start: pd.Timestamp | None = None,
                end: pd.Timestamp | None = None, side: str = "bid") -> pd.DataFrame:
        """Bars of `tf` that OPEN in [start, end). Cut on M1 first, so a bar at
        the edge of the window is built only from minutes inside it."""
        m1 = self._minutes(symbol, side)
        if start is not None:
            m1 = m1[m1.index >= start]
        if end is not None:
            m1 = m1[m1.index < end]
        return resample(m1, tf)

    def get_ohlc(self, symbol: str, tf: str, bars: int = 500) -> pd.DataFrame:
        """The last `bars` bars of the stored history. Every one of them has
        closed: the data is a past download, not a live feed."""
        m1 = self._minutes(symbol, "bid")
        # Generous cut before resampling: the market is open about 23 of 24 hours
        # on about 5 of 7 days, so 2x the nominal span always covers `bars`.
        span = pd.Timedelta(minutes=TF_MINUTES[tf] * bars * 2) + pd.Timedelta(days=7)
        return resample(m1[m1.index >= m1.index[-1] - span], tf).iloc[-bars:]
