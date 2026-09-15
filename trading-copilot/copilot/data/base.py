"""DataSource protocol — all data providers implement this interface."""

from typing import Protocol, runtime_checkable
import pandas as pd

# 1w added Aug 2026: the 1h3m setup wants "1W and 1D agree" as an HTF filter,
# and nothing in the stack could fetch a weekly bar.
VALID_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"}

# Bar length in minutes. Lives here rather than in the backtest engine because
# the data layer needs it too (sizing a batched fetch window in milliseconds),
# and a second copy is a second thing to forget when a timeframe is added.
TF_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15,
    "30m": 30, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080,
}


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
