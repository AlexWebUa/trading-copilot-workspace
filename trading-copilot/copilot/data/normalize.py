"""
Canonical OHLCV DataFrame schema used everywhere in trading-copilot.

Index: DatetimeIndex, UTC, name="ts"
Columns: open, high, low, close, volume  (all float64)

All detectors expect exactly this shape. Fixtures must use it too.
"""

import pandas as pd

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

# Binance /api/v3/klines returns 12 fields per row
_BINANCE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "num_trades",
    "taker_buy_base_vol", "taker_buy_quote_vol", "ignore",
]


def normalize_binance(raw: list[list]) -> pd.DataFrame:
    """Convert raw Binance klines list-of-lists to canonical DataFrame."""
    df = pd.DataFrame(raw, columns=_BINANCE_COLUMNS)
    df = df[["open_time"] + OHLCV_COLUMNS].copy()
    for col in OHLCV_COLUMNS:
        df[col] = df[col].astype("float64")
    df["ts"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    df = df.drop(columns=["open_time"]).set_index("ts")
    return df[OHLCV_COLUMNS]


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
