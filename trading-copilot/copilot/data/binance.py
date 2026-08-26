"""
Binance public REST data source — USD-M Futures (fapi.binance.com) or spot
(api.binance.com).

Futures is the default: perpetuals (BTCUSDT, ETHUSDT, …) are what the
discretionary trader actually trades. Spot exists because a growing set of
listings is spot-only — tokenised stocks (QQQBUSDT) and some commodities — and
a futures request for one of those fails with `-1121 Invalid symbol`.

Market selection, highest precedence first:
  1. `market=` passed to BinanceSource / fetch helpers
  2. `COPILOT_MARKET` env var — how the REPL's `--market` flag reaches an
     in-process registry AND the MCP server the cli backend spawns
  3. "futures"

No auth required. Rate limit: 2400 req/min weight.
Endpoints: GET /fapi/v1/klines · GET /api/v3/klines
"""

import os
import time

import httpx
import pandas as pd

from copilot.data.base import assert_valid_tf
from copilot.data.cache import OHLCCache
from copilot.data.normalize import make_empty, normalize_binance, normalize_binance_with_delta

# USD-M perpetual futures — primary
_FUTURES_URL = "https://fapi.binance.com"
_FUTURES_ENDPOINT = "/fapi/v1/klines"

# Spot
_SPOT_URL = "https://api.binance.com"
_SPOT_ENDPOINT = "/api/v3/klines"

class SymbolNotOnMarket(RuntimeError):
    """The symbol exists on Binance, just not on the market being queried."""


# Max klines per request, per market. Spot caps at 1000 and futures at 1500 —
# and neither errors on a larger `limit`, it just returns fewer rows. Code that
# assumed 1500 everywhere silently truncated every spot range longer than 1000
# bars, and stopped paginating because the short page looked like end-of-history.
_BATCH_LIMITS = {"futures": 1500, "spot": 1000}

MARKETS = ("futures", "spot")
DEFAULT_MARKET = "futures"


def resolve_market(market: str | None = None) -> str:
    """Explicit argument > COPILOT_MARKET > futures."""
    value = (market or os.getenv("COPILOT_MARKET") or DEFAULT_MARKET).strip().lower()
    if value not in MARKETS:
        raise ValueError(f"Unknown market {value!r}. Expected one of: {', '.join(MARKETS)}")
    return value


def _to_ms(t) -> int:
    """Convert ISO string, datetime, pd.Timestamp, or int (ms) to Unix milliseconds."""
    if isinstance(t, int):
        return t
    ts = pd.Timestamp(t)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return int(ts.timestamp() * 1000)


# Map copilot TF notation → Binance interval param
_TF_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m",
    "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w",
}


class BinanceSource:
    """Fetches OHLCV data from Binance USD-M Futures REST API with disk caching."""

    def __init__(
        self,
        cache: OHLCCache | None = None,
        timeout: float = 10.0,
        market: str | None = None,  # "futures" | "spot"; None → resolve_market()
    ):
        self._cache = cache or OHLCCache()
        self._timeout = timeout
        market = resolve_market(market)
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


    @property
    def market(self) -> str:
        return self._market

    def _get(self, client: httpx.Client, params: dict) -> list:
        """GET klines, turning "symbol not on this market" into actionable advice.

        Binance answers -1121 for a symbol that simply lives on the other market
        — spot-only listings (tokenised stocks, some commodities) are the common
        case. The raw 400 says nothing about that, so the trader would read it as
        "the symbol does not exist".
        """
        resp = client.get(f"{self._base_url}{self._endpoint}", params=params)
        if resp.status_code == 400:
            try:
                code = resp.json().get("code")
            except Exception:
                code = None
            if code == -1121:
                other = "spot" if self._market == "futures" else "futures"
                raise SymbolNotOnMarket(
                    f"{params.get('symbol')} is not listed on Binance {self._market}. "
                    f"Try the {other} market (REPL: `market {other}`, "
                    f"CLI: `--market {other}`, env: COPILOT_MARKET={other})."
                )
        resp.raise_for_status()
        return resp.json()

    def get_ohlc(
        self,
        symbol: str,
        tf: str,
        bars: int = 500,
        start_time=None,
        end_time=None,
    ) -> pd.DataFrame:
        assert_valid_tf(tf)
        symbol = symbol.upper()

        if start_time is not None or end_time is not None:
            if start_time is not None and end_time is None:
                raise ValueError(
                    "end_time is required when start_time is provided — "
                    "open-ended range queries could fetch excessive historical data."
                )
            start_ms = _to_ms(start_time) if start_time is not None else None
            end_ms = _to_ms(end_time) if end_time is not None else None
            cached = self._cache.get_range(self.source_id, symbol, tf, start_ms, end_ms)
            if cached is not None:
                return cached
            df = self._fetch_range(symbol, tf, start_ms, end_ms)
            self._cache.put_range(self.source_id, symbol, tf, start_ms, end_ms, df)
            return df

        cached = self._cache.get(self.source_id, symbol, tf, bars)
        if cached is not None:
            return cached

        df = self._fetch(symbol, tf, bars)
        self._cache.put(self.source_id, symbol, tf, bars, df)
        return df

    def get_ohlc_with_delta(self, symbol: str, tf: str, bars: int = 200) -> pd.DataFrame:
        """Like get_ohlc but with buy_vol/sell_vol/delta columns, cached.

        P0-6: delta data goes through the same disk cache as plain OHLCV
        (separate cache namespace so column sets don't collide).
        """
        assert_valid_tf(tf)
        symbol = symbol.upper()
        source_id = f"{self.source_id}_delta"

        cached = self._cache.get(source_id, symbol, tf, bars)
        if cached is not None:
            return cached

        if bars > self._batch_limit:
            df = self._paginate_back(symbol, tf, bars, normalize_binance_with_delta)
        else:
            interval = _TF_MAP[tf]
            params = {"symbol": symbol, "interval": interval, "limit": bars}
            with httpx.Client(timeout=self._timeout) as client:
                raw = self._get(client, params)
            df = normalize_binance_with_delta(raw)
        self._cache.put(source_id, symbol, tf, bars, df)
        return df


    @property
    def _batch_limit(self) -> int:
        return _BATCH_LIMITS[self._market]

    def _paginate_back(self, symbol: str, tf: str, bars: int, normalizer) -> pd.DataFrame:
        """Walk backwards in 1500-bar pages until *bars* are collected.

        A single klines request is capped at 1500 by Binance. Passing a larger
        `limit` is not an error — the API just returns 1500, so a request for
        5000 bars silently produced 1499 and every caller believed it had the
        window it asked for. Backtests over multi-month samples were quietly
        running on a fraction of the data.
        """
        interval = _TF_MAP[tf]
        frames: list[pd.DataFrame] = []
        remaining = bars
        end_ms: int | None = None

        with httpx.Client(timeout=max(self._timeout, 30.0)) as client:
            while remaining > 0:
                params: dict = {
                    "symbol": symbol,
                    "interval": interval,
                    "limit": min(remaining, self._batch_limit),
                }
                if end_ms is not None:
                    params["endTime"] = end_ms

                raw = self._get(client, params)
                if not raw:
                    break

                frames.append(normalizer(raw))
                remaining -= len(raw)

                if len(raw) < params["limit"]:
                    break  # start of available history

                end_ms = int(raw[0][0]) - 1
                if remaining > 0:
                    time.sleep(0.1)  # rate-limit courtesy

        if not frames:
            return make_empty()

        result = pd.concat(frames)
        result = result[~result.index.duplicated(keep="first")]
        return result.sort_index()

    def _fetch(self, symbol: str, tf: str, bars: int) -> pd.DataFrame:
        if bars > self._batch_limit:
            return self._paginate_back(symbol, tf, bars, normalize_binance)
        interval = _TF_MAP[tf]
        params = {"symbol": symbol, "interval": interval, "limit": bars}
        with httpx.Client(timeout=self._timeout) as client:
            return normalize_binance(self._get(client, params))

    def _fetch_range(
        self,
        symbol: str,
        tf: str,
        start_ms: int | None,
        end_ms: int | None,
    ) -> pd.DataFrame:
        """Fetch all bars in [start_ms, end_ms], paginating forward in batches of 1500."""
        interval = _TF_MAP[tf]
        frames: list[pd.DataFrame] = []
        current_start = start_ms

        with httpx.Client(timeout=30.0) as client:
            while True:
                params: dict = {
                    "symbol": symbol,
                    "interval": interval,
                    "limit": self._batch_limit,
                }
                if current_start is not None:
                    params["startTime"] = current_start
                if end_ms is not None:
                    params["endTime"] = end_ms

                raw = self._get(client, params)
                if not raw:
                    break

                batch = normalize_binance(raw)
                frames.append(batch)

                if len(raw) < self._batch_limit:
                    break  # received fewer than max → no more pages

                last_open_ms = int(raw[-1][0])
                if end_ms is not None and last_open_ms >= end_ms:
                    break

                current_start = last_open_ms + 1
                time.sleep(0.05)

        if not frames:
            return make_empty()

        result = pd.concat(frames)
        result = result[~result.index.duplicated(keep="first")]
        result = result.sort_index()

        if end_ms is not None:
            end_ts = pd.Timestamp(end_ms, unit="ms", tz="UTC")
            result = result[result.index <= end_ts]

        return result


def fetch_ohlcv_with_delta(
    symbol: str,
    tf: str,
    bars: int = 200,
    market: str | None = None,
) -> pd.DataFrame:
    """Fetch klines and return OHLCV + per-bar delta columns.

    Uses taker_buy_base_vol from the klines response — exact candle-level
    delta from Binance, no approximation or tick-data required.

    Returned columns: open, high, low, close, volume, buy_vol, sell_vol, delta

    P0-6: thin wrapper around BinanceSource.get_ohlc_with_delta so the
    delta path shares the disk cache. Prefer calling the method directly
    when you already hold a BinanceSource.
    """
    return BinanceSource(market=market).get_ohlc_with_delta(symbol, tf, bars)


_MAX_BATCHED_BARS = 100_000



# Binance answers 429 when a burst of requests exceeds its weight budget. A
# single backtest paginating 95k 3m bars is 64 requests; several arms running
# in parallel multiply that and trip the limit mid-run. Without a retry the
# whole run dies — and worse, the caller used to swallow the failure and
# backtest a different strategy (see engine._run_loop). Back off and continue.
_RETRY_STATUSES = frozenset({429, 418, 500, 502, 503, 504})
_MAX_RETRIES = 6


def _get_batch_with_retry(client, url: str, params: dict) -> list:
    """GET one kline page, backing off on rate limits and transient 5xx."""
    delay = 1.0
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = client.get(url, params=params)
            if resp.status_code in _RETRY_STATUSES:
                # Binance sends Retry-After on 418; honour it when present.
                wait = float(resp.headers.get("Retry-After", 0)) or delay
                time.sleep(min(wait, 60.0))
                delay = min(delay * 2, 60.0)
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _RETRY_STATUSES:
                raise
            last_exc = exc
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
        except httpx.TransportError as exc:      # timeouts, connection resets
            last_exc = exc
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
    raise RuntimeError(
        f"Binance kline request failed after {_MAX_RETRIES} attempts: {url} {params}"
    ) from last_exc


def fetch_ohlcv_batched(
    symbol: str,
    tf: str,
    total_bars: int,
    market: str | None = None,
    batch_size: int | None = None,
    end_ms: int | None = None,
) -> pd.DataFrame:
    """
    Fetch up to total_bars of OHLCV data in batches of batch_size,
    paginating backwards from `end_ms` (default: the most recent bar).

    `end_ms` exists for date-ranged backtests. Without it the LTF frame always
    ends at "now" while the HTF frame has been trimmed to a historical window,
    so the two timeframes describe different periods and the entry scan looks
    for confirmation in bars that postdate the signal by months.
    Deduplicates and sorts by timestamp ascending.
    Returns a single concatenated DataFrame.

    Caps total_bars at 100 000 and prints a warning if exceeded.
    Sleeps 0.1 s between requests to respect rate limits.
    """
    if total_bars > _MAX_BATCHED_BARS:
        print(
            f"WARNING: LTF bars capped at 100 000 ({tf}). "
            f"Consider reducing signal TF bars or using 5m instead of 1m."
        )
        total_bars = _MAX_BATCHED_BARS

    assert_valid_tf(tf)
    symbol = symbol.upper()
    interval = _TF_MAP[tf]
    market = resolve_market(market)

    batch_size = batch_size or _BATCH_LIMITS[market]

    if market == "futures":
        base_url, endpoint = _FUTURES_URL, _FUTURES_ENDPOINT
    else:
        base_url, endpoint = _SPOT_URL, _SPOT_ENDPOINT

    frames: list[pd.DataFrame] = []
    remaining = total_bars
    end_time_ms: int | None = end_ms  # None → most recent bar

    with httpx.Client(timeout=30.0) as client:
        while remaining > 0:
            limit = min(remaining, batch_size)
            params: dict = {"symbol": symbol, "interval": interval, "limit": limit}
            if end_time_ms is not None:
                params["endTime"] = end_time_ms

            raw = _get_batch_with_retry(client, f"{base_url}{endpoint}", params)
            if not raw:
                break

            batch_df = normalize_binance(raw)
            frames.append(batch_df)
            remaining -= len(raw)

            if len(raw) < limit:
                break  # reached the beginning of available history

            # Paginate backwards: set endTime to 1 ms before the oldest bar's open_time
            end_time_ms = int(raw[0][0]) - 1

            if remaining > 0:
                time.sleep(0.1)

    if not frames:
        return make_empty()

    result = pd.concat(frames)
    result = result[~result.index.duplicated(keep="first")]
    return result.sort_index()


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
