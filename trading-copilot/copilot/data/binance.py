"""
Binance public REST data source — USD-M Futures (fapi.binance.com).

Uses perpetual futures data (BTCUSDT, ETHUSDT, etc.) which is what
discretionary traders actually trade. No auth required.
Rate limit: 2400 req/min weight.
Endpoint: GET /fapi/v1/klines

Spot fallback: set market="spot" to use api.binance.com instead.
"""

import httpx
import pandas as pd

from copilot.data.base import assert_valid_tf
from copilot.data.cache import OHLCCache
from copilot.data.normalize import normalize_binance, normalize_binance_with_delta

# USD-M perpetual futures — primary
_FUTURES_URL = "https://fapi.binance.com"
_FUTURES_ENDPOINT = "/fapi/v1/klines"

# Spot fallback
_SPOT_URL = "https://api.binance.com"
_SPOT_ENDPOINT = "/api/v3/klines"

# Map copilot TF notation → Binance interval param
_TF_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m",
    "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d",
}


class BinanceSource:
    """Fetches OHLCV data from Binance USD-M Futures REST API with disk caching."""

    def __init__(
        self,
        cache: OHLCCache | None = None,
        timeout: float = 10.0,
        market: str = "futures",  # "futures" | "spot"
    ):
        self._cache = cache or OHLCCache()
        self._timeout = timeout
        self._market = market
        if market == "futures":
            self._base_url = _FUTURES_URL
            self._endpoint = _FUTURES_ENDPOINT
            self.source_id = "binance_futures"
        else:
            self._base_url = _SPOT_URL
            self._endpoint = _SPOT_ENDPOINT
            self.source_id = "binance_spot"

    def supports(self, symbol: str) -> bool:
        return symbol.endswith("USDT") or symbol.endswith("BTC")

    def get_ohlc(self, symbol: str, tf: str, bars: int = 500) -> pd.DataFrame:
        assert_valid_tf(tf)
        symbol = symbol.upper()

        cached = self._cache.get(self.source_id, symbol, tf, bars)
        if cached is not None:
            return cached

        df = self._fetch(symbol, tf, bars)
        self._cache.put(self.source_id, symbol, tf, bars, df)
        return df

    def _fetch(self, symbol: str, tf: str, bars: int) -> pd.DataFrame:
        interval = _TF_MAP[tf]
        params = {"symbol": symbol, "interval": interval, "limit": min(bars, 1500)}
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(f"{self._base_url}{self._endpoint}", params=params)
            resp.raise_for_status()
        return normalize_binance(resp.json())


def fetch_ohlcv_with_delta(
    symbol: str,
    tf: str,
    bars: int = 200,
    market: str = "futures",
) -> pd.DataFrame:
    """Fetch klines and return OHLCV + per-bar delta columns.

    Uses taker_buy_base_vol from the klines response — exact candle-level
    delta from Binance, no approximation or tick-data required.

    Returned columns: open, high, low, close, volume, buy_vol, sell_vol, delta
    """
    assert_valid_tf(tf)
    symbol = symbol.upper()
    interval = _TF_MAP[tf]

    if market == "futures":
        base_url, endpoint = _FUTURES_URL, _FUTURES_ENDPOINT
    else:
        base_url, endpoint = _SPOT_URL, _SPOT_ENDPOINT

    params = {"symbol": symbol, "interval": interval, "limit": min(bars, 1500)}
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{base_url}{endpoint}", params=params)
        resp.raise_for_status()
    return normalize_binance_with_delta(resp.json())


def fetch_multi_tf(
    symbol: str,
    tfs: list[str] | None = None,
    bars: int = 500,
    source: BinanceSource | None = None,
) -> dict[str, pd.DataFrame]:
    """Fetch multiple timeframes in sequence. Returns {tf: DataFrame}."""
    tfs = tfs or ["1d", "4h", "1h", "15m", "3m"]
    src = source or BinanceSource()
    return {tf: src.get_ohlc(symbol, tf, bars) for tf in tfs}
