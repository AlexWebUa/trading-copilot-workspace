"""
Canonical OHLCV DataFrame schema used everywhere in trading-copilot.

Index: DatetimeIndex, UTC, name="ts"
Columns: open, high, low, close, volume  (all float64)

All detectors expect exactly this shape. Fixtures must use it too.
"""

import time

import pandas as pd

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

# Binance /api/v3/klines returns 12 fields per row
_BINANCE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "num_trades",
    "taker_buy_base_vol", "taker_buy_quote_vol", "ignore",
]

# close_time is field index 6 in each raw kline row
_CLOSE_TIME_IDX = 6


def _drop_forming(raw: list[list], include_forming: bool) -> list[list]:
    """Drop the last kline if it hasn't closed yet (close_time in the future).

    Binance always returns the in-progress candle as the final row. Analyzing
    it violates the "entry only on candle CLOSE" rule — every signal computed
    on it can repaint. Historical ranges are unaffected: their last kline is
    already closed, so nothing is dropped.
    """
    if include_forming or not raw:
        return raw
    now_ms = int(time.time() * 1000)
    if int(raw[-1][_CLOSE_TIME_IDX]) > now_ms:
        return raw[:-1]
    return raw


def normalize_binance(raw: list[list], include_forming: bool = False) -> pd.DataFrame:
    """Convert raw Binance klines list-of-lists to canonical DataFrame.

    The forming (not yet closed) last candle is dropped unless
    include_forming=True.
    """
    raw = _drop_forming(raw, include_forming)
    if not raw:
        return make_empty()
    df = pd.DataFrame(raw, columns=_BINANCE_COLUMNS)
    df = df[["open_time"] + OHLCV_COLUMNS].copy()
    for col in OHLCV_COLUMNS:
        df[col] = df[col].astype("float64")
    df["ts"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    df = df.drop(columns=["open_time"]).set_index("ts")
    return df[OHLCV_COLUMNS]


DELTA_COLUMNS = ["buy_vol", "sell_vol", "delta"]


def normalize_binance_with_delta(raw: list[list], include_forming: bool = False) -> pd.DataFrame:
    """Like normalize_binance but also includes buy_vol, sell_vol, delta columns.

    buy_vol  = taker_buy_base_vol  (aggressive market buys, Ask side)
    sell_vol = volume - buy_vol    (aggressive market sells, Bid side)
    delta    = buy_vol - sell_vol  (positive = buyers dominated)

    These come from the klines response directly — no approximation needed.
    The forming (not yet closed) last candle is dropped unless
    include_forming=True.
    """
    raw = _drop_forming(raw, include_forming)
    if not raw:
        df = make_empty()
        for col in DELTA_COLUMNS:
            df[col] = pd.Series(dtype="float64")
        return df
    df = pd.DataFrame(raw, columns=_BINANCE_COLUMNS)
    for col in OHLCV_COLUMNS + ["taker_buy_base_vol"]:
        df[col] = df[col].astype("float64")
    df["ts"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    df = df.drop(columns=["open_time"]).set_index("ts")
    df["buy_vol"] = df["taker_buy_base_vol"]
    df["sell_vol"] = df["volume"] - df["buy_vol"]
    df["delta"] = df["buy_vol"] - df["sell_vol"]
    return df[OHLCV_COLUMNS + DELTA_COLUMNS]


def validate(df: pd.DataFrame) -> None:
    """Raise if df doesn't match the canonical schema."""
    missing = [c for c in OHLCV_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"OHLCV DataFrame missing columns: {missing}")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("DataFrame index must be DatetimeIndex")
    if df.index.tz is None:
        raise ValueError("DataFrame index must be timezone-aware (UTC)")


def make_empty() -> pd.DataFrame:
    df = pd.DataFrame(columns=OHLCV_COLUMNS)
    df.index = pd.DatetimeIndex([], tz="UTC", name="ts")
    return df
