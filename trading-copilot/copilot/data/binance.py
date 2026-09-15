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

from copilot.data.base import TF_MINUTES, assert_valid_tf
from copilot.data.cache import BatchedOHLCStore, OHLCCache
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


def _paginate_back_window(
    client,
    url: str,
    base_params: dict,
    batch_size: int,
    end_time_ms: int | None,
    max_bars: int | None = None,
    stop_at_ms: int | None = None,
) -> tuple[list[pd.DataFrame], bool]:
    """Walk backwards from `end_time_ms`, one kline page at a time.

    Stops on whichever comes first: `max_bars` collected, a page whose oldest
    bar is at or before `stop_at_ms` (the caller already holds everything
    older), or a short page (the beginning of available history).

    Returns (frames_newest_first, reached_history_start).
    """
    frames: list[pd.DataFrame] = []
    collected = 0
    reached_history_start = False

    while True:
        if max_bars is not None:
            remaining = max_bars - collected
            if remaining <= 0:
                break
            limit = min(remaining, batch_size)
        else:
            limit = batch_size

        params = dict(base_params)
        params["limit"] = limit
        if end_time_ms is not None:
            params["endTime"] = end_time_ms

        raw = _get_batch_with_retry(client, url, params)
        if not raw:
            break

        frames.append(normalize_binance(raw))
        collected += len(raw)
        oldest_open_ms = int(raw[0][0])

        if len(raw) < limit:
            reached_history_start = True
            break
        if stop_at_ms is not None and oldest_open_ms <= stop_at_ms:
            break

        # Paginate backwards: endTime is inclusive on open_time.
        end_time_ms = oldest_open_ms - 1
        time.sleep(0.1)

    return frames, reached_history_start


def _endpoint_for(market: str) -> str:
    if market == "futures":
        return f"{_FUTURES_URL}{_FUTURES_ENDPOINT}"
    return f"{_SPOT_URL}{_SPOT_ENDPOINT}"


def fetch_ohlcv_batched(
    symbol: str,
    tf: str,
    total_bars: int,
    market: str | None = None,
    batch_size: int | None = None,
    end_ms: int | None = None,
    store: "BatchedOHLCStore | None" = None,
    use_cache: bool = True,
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

    Results go through `BatchedOHLCStore` (disk, coverage-based) unless
    `use_cache=False`. This is the engine's LTF path: without it every rule arm
    re-downloaded the same ~100 000 bars over ~67 requests, which is both the
    slowest part of a research run and the reason arms could not be run more
    than three wide without tripping Binance rate limits.
    """
    if total_bars > _MAX_BATCHED_BARS:
        print(
            f"WARNING: LTF bars capped at 100 000 ({tf}). "
            f"Consider reducing signal TF bars or using 5m instead of 1m."
        )
        total_bars = _MAX_BATCHED_BARS

    assert_valid_tf(tf)
    symbol = symbol.upper()
    market = resolve_market(market)

    base_params = {"symbol": symbol, "interval": _TF_MAP[tf]}
    batch_size = batch_size or _BATCH_LIMITS[market]
    url = _endpoint_for(market)

    if not use_cache:
        with httpx.Client(timeout=30.0) as client:
            frames, _ = _paginate_back_window(
                client, url, base_params, batch_size, end_ms, max_bars=total_bars
            )
        return _stitch(frames)

    source_id = f"binance_{market}"
    store = store or BatchedOHLCStore()
    tf_ms = TF_MINUTES[tf] * 60_000

    # The window the caller is asking for, in absolute time. `end_ms` is
    # inclusive on open_time, matching Binance's endTime.
    needed_end_ms = end_ms if end_ms is not None else int(time.time() * 1000)
    # `total_bars` bars ENDING at needed_end_ms, inclusive — so the first one
    # opens (total_bars - 1) bars earlier, not total_bars. Off by one here and
    # every repeat request re-fetches a head page for a single missing bar.
    needed_start_ms = needed_end_ms - (total_bars - 1) * tf_ms

    loaded = store.load(source_id, symbol, tf)
    stored: pd.DataFrame | None = None
    at_history_start = False
    if loaded is not None:
        stored, at_history_start = loaded
        covered_start_ms = int(stored.index[0].timestamp() * 1000)
        covered_end_ms = int(stored.index[-1].timestamp() * 1000)
        # Disjoint from what we hold → replace rather than bridge. Bridging
        # would silently download every bar in between.
        if covered_end_ms < needed_start_ms or covered_start_ms > needed_end_ms:
            stored, at_history_start = None, False

    needs_tail = stored is None or int(stored.index[-1].timestamp() * 1000) + tf_ms <= needed_end_ms
    needs_head = stored is None or (
        int(stored.index[0].timestamp() * 1000) > needed_start_ms and not at_history_start
    )

    if needs_tail or needs_head:
        with httpx.Client(timeout=30.0) as client:
            if stored is None:
                frames, reached_start = _paginate_back_window(
                    client, url, base_params, batch_size, needed_end_ms, max_bars=total_bars
                )
                merged = _stitch(frames)
                at_history_start = reached_start
            else:
                covered_start_ms = int(stored.index[0].timestamp() * 1000)
                covered_end_ms = int(stored.index[-1].timestamp() * 1000)
                pieces = [stored]

                # Tail: bars newer than what we hold. A window ending "now"
                # always lands here, and costs exactly the pages it needs.
                # `stop_at_ms` makes the tail overlap the stored range, which is
                # what keeps the merged frame contiguous.
                if needs_tail:
                    tail, _ = _paginate_back_window(
                        client, url, base_params, batch_size,
                        needed_end_ms, stop_at_ms=covered_end_ms,
                    )
                    pieces.extend(tail)

                # Head: bars older than what we hold, unless the series itself
                # starts inside the stored range.
                if needs_head:
                    head_bars = int((covered_start_ms - needed_start_ms) / tf_ms) + 1
                    head, reached_start = _paginate_back_window(
                        client, url, base_params, batch_size,
                        covered_start_ms - 1, max_bars=head_bars,
                    )
                    pieces.extend(head)
                    at_history_start = at_history_start or reached_start

                merged = _stitch(pieces)

        if merged.empty:
            return merged
        # Only on an actual fetch: rewriting a 100k-row parquet on every cache
        # hit would hand back most of what the cache just saved.
        store.save(source_id, symbol, tf, merged, at_history_start)
    else:
        merged = stored

    window = merged[merged.index <= pd.Timestamp(needed_end_ms, unit="ms", tz="UTC")]
    return window.tail(total_bars)


def _stitch(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate kline pages into one ascending, duplicate-free frame."""
    frames = [f for f in frames if not f.empty]
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
