"""DataSource protocol — all data providers implement this interface."""

from typing import Protocol, runtime_checkable
import pandas as pd

VALID_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"}


@runtime_checkable
class DataSource(Protocol):
    def get_ohlc(self, symbol: str, tf: str, bars: int = 500) -> pd.DataFrame:
        """Return canonical OHLCV DataFrame (see normalize.py)."""
        ...

    def supports(self, symbol: str) -> bool:
        """Return True if this source can serve the given symbol."""
        ...


def assert_valid_tf(tf: str) -> None:
    if tf not in VALID_TIMEFRAMES:
        raise ValueError(
            f"Unknown timeframe '{tf}'. Valid: {sorted(VALID_TIMEFRAMES)}"
        )
