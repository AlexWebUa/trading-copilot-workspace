"""Parquet-based disk cache for OHLCV data. TTL per timeframe."""

import hashlib
import json
import os
import time
from pathlib import Path

import pandas as pd

from copilot.data.normalize import validate

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "trading-copilot"


def _default_cache_dir() -> Path:
    """Resolve the cache root at call time, not at import time.

    `_DEFAULT_CACHE_DIR` is frozen when the module is first imported, so a test
    that redirects `Path.home()` afterwards does not reach it — an unguarded
    default would write fixture frames into the trader's real cache.
    """
    return Path.home() / ".cache" / "trading-copilot"

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


# ---------------------------------------------------------------------------
# Batched (LTF) store — coverage-based, not request-keyed
# ---------------------------------------------------------------------------

# Bump when the stored layout changes or a fetch bug means existing frames hold
# wrong data. Independent of _CACHE_VERSION: different files, different keys.
_BATCHED_VERSION = 1


def _batched_paths(cache_dir: Path, source: str, symbol: str, tf: str) -> tuple[Path, Path]:
    key = f"v{_BATCHED_VERSION}/{source}/{symbol}/{tf}"
    digest = hashlib.md5(key.encode()).hexdigest()[:12]
    stem = cache_dir / f"batched_{source}_{symbol}_{tf}_{digest}"
    return stem.with_suffix(".parquet"), stem.with_suffix(".json")


class BatchedOHLCStore:
    """One accumulating contiguous frame per (source, symbol, tf).

    `OHLCCache` keys on the exact request and expires on a per-timeframe TTL.
    That is right for a 500-bar live pull and useless for the backtest engine's
    LTF frame — ~100 000 3m bars fetched in 67 requests, once per rule arm. The
    request key contains the window end, which moves every time the HTF frame
    gains a bar, i.e. every hour of a multi-hour research run, so a
    request-keyed entry is essentially never hit twice.

    This store answers any request whose window lies inside what it already
    holds, and otherwise fetches only the missing edges. Historical klines are
    immutable, so the interior needs no TTL; the right edge polices itself,
    because a window ending "now" always asks for a bar the store cannot have
    and therefore always triggers a small tail fetch.

    Contiguity is an invariant, not an assumption: a request that does not
    overlap the stored range REPLACES it rather than bridging to it. Bridging
    would download the months in between, which nobody asked for.
    """

    def __init__(self, cache_dir: Path | None = None):
        env_dir = os.getenv("TRADING_COPILOT_CACHE_DIR")
        self._dir = Path(env_dir).expanduser() if env_dir else (cache_dir or _default_cache_dir())
        self._dir.mkdir(parents=True, exist_ok=True)

    def load(self, source: str, symbol: str, tf: str) -> tuple[pd.DataFrame, bool] | None:
        """Return (frame, reached_history_start), or None if nothing usable."""
        parquet_path, meta_path = _batched_paths(self._dir, source, symbol, tf)
        if not parquet_path.exists():
            return None
        try:
            df = pd.read_parquet(parquet_path)
        except Exception:
            # A half-written or version-mismatched file is a cache miss, not an
            # error: the caller can always re-fetch.
            return None
        if df.empty:
            return None
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        at_history_start = False
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            at_history_start = bool(meta.get("at_history_start", False))
        except Exception:
            pass
        return df, at_history_start

    def save(
        self,
        source: str,
        symbol: str,
        tf: str,
        df: pd.DataFrame,
        at_history_start: bool,
    ) -> None:
        if df.empty:
            return
        validate(df)
        parquet_path, meta_path = _batched_paths(self._dir, source, symbol, tf)
        # Atomic: research runs go three arms wide against the same series, and
        # a reader hitting a half-written parquet would take it as a miss and
        # re-download 100k bars. os.replace is atomic on both POSIX and Windows.
        tmp = parquet_path.with_suffix(f".parquet.tmp{os.getpid()}")
        df.to_parquet(tmp)
        os.replace(tmp, parquet_path)
        meta_tmp = meta_path.with_suffix(f".json.tmp{os.getpid()}")
        meta_tmp.write_text(
            json.dumps({"at_history_start": bool(at_history_start)}),
            encoding="utf-8",
        )
        os.replace(meta_tmp, meta_path)
