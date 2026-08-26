"""Parquet-based disk cache for OHLCV data. TTL per timeframe."""

import hashlib
import os
import time
from pathlib import Path

import pandas as pd

from copilot.data.normalize import validate

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "trading-copilot"

# Bump when a fetch-layer bug means existing entries hold wrong data.
# v2 (2026-08): pre-pagination entries capped every request at 1500 bars, so a
# cached "5000-bar" frame actually held 1499 — silently, under the right key.
# v3 (2026-08): spot entries could hold a range truncated at 1000 bars — the
# fetch layer assumed the futures limit of 1500 on both markets.
_CACHE_VERSION = 3

# TTL in seconds per timeframe
_DEFAULT_TTL: dict[str, int] = {
    "1m": 60, "3m": 60, "5m": 60,
    "15m": 300, "1h": 300,
    "4h": 3600, "1d": 3600, "1w": 3600,
}


def _cache_path(cache_dir: Path, source: str, symbol: str, tf: str, bars: int) -> Path:
    key = f"v{_CACHE_VERSION}/{source}/{symbol}/{tf}/{bars}"
    digest = hashlib.md5(key.encode()).hexdigest()[:12]
    return cache_dir / f"{source}_{symbol}_{tf}_{bars}_{digest}.parquet"


def _range_cache_path(
    cache_dir: Path,
    source: str,
    symbol: str,
    tf: str,
    start_ms: int | None,
    end_ms: int | None,
) -> Path:
    key = f"v{_CACHE_VERSION}/{source}/{symbol}/{tf}/{start_ms}/{end_ms}"
    digest = hashlib.md5(key.encode()).hexdigest()[:12]
    return cache_dir / f"{source}_{symbol}_{tf}_range_{digest}.parquet"


class OHLCCache:
    def __init__(
        self,
        cache_dir: Path | None = None,
        ttl: dict[str, int] | None = None,
    ):
        env_dir = os.getenv("TRADING_COPILOT_CACHE_DIR")
        self._dir = Path(env_dir).expanduser() if env_dir else (cache_dir or _DEFAULT_CACHE_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl or _DEFAULT_TTL

    def get(self, source: str, symbol: str, tf: str, bars: int) -> pd.DataFrame | None:
        path = _cache_path(self._dir, source, symbol, tf, bars)
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > self._ttl.get(tf, 300):
            return None
        df = pd.read_parquet(path)
        # Re-attach timezone if stripped by parquet
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df

    def put(self, source: str, symbol: str, tf: str, bars: int, df: pd.DataFrame) -> None:
        validate(df)
        path = _cache_path(self._dir, source, symbol, tf, bars)
        df.to_parquet(path)

    def invalidate(self, source: str, symbol: str, tf: str, bars: int) -> None:
        path = _cache_path(self._dir, source, symbol, tf, bars)
        if path.exists():
            path.unlink()

    def get_range(
        self,
        source: str,
        symbol: str,
        tf: str,
        start_ms: int | None,
        end_ms: int | None,
    ) -> pd.DataFrame | None:
        path = _range_cache_path(self._dir, source, symbol, tf, start_ms, end_ms)
        if not path.exists():
            return None
        # Historical ranges are immutable — 24h TTL is generous
        age = time.time() - path.stat().st_mtime
        if age > 86400:
            return None
        df = pd.read_parquet(path)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df

    def put_range(
        self,
        source: str,
        symbol: str,
        tf: str,
        start_ms: int | None,
        end_ms: int | None,
        df: pd.DataFrame,
    ) -> None:
        validate(df)
        path = _range_cache_path(self._dir, source, symbol, tf, start_ms, end_ms)
        df.to_parquet(path)
