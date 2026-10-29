"""Pick the data source for a symbol — the one place that knows which is which."""

from __future__ import annotations

import pandas as pd

from copilot.data.dukascopy import DukascopySource

# Instruments read from the offline Dukascopy download rather than from Binance.
OFFLINE_SYMBOLS = frozenset({"XAUUSD"})


def source_for(symbol: str, until: str | pd.Timestamp | None = None):
    """`BinanceSource` for crypto, `DukascopySource` for the offline symbols.

    `until` caps what an offline source will ever return (see `DukascopySource`);
    Binance requests are already bounded by the caller's own window.
    """
    if symbol.upper() in OFFLINE_SYMBOLS:
        ceiling = pd.Timestamp(until) if until is not None else None
        if ceiling is not None and ceiling.tzinfo is None:
            ceiling = ceiling.tz_localize("UTC")
        return DukascopySource(until=ceiling)
    from copilot.data.binance import BinanceSource
    return BinanceSource()
