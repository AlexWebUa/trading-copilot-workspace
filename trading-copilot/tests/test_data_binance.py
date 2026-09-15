"""
Tests for copilot/data/binance.py — fetch_ohlcv_batched.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from copilot.data.binance import BinanceSource, _to_ms, fetch_ohlcv_batched
from copilot.data.cache import OHLCCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kline(open_ms: int, price: float) -> list:
    """Build a minimal Binance kline row (12 fields)."""
    return [
        open_ms,          # open_time
        str(price),       # open
        str(price + 1),   # high
        str(price - 1),   # low
        str(price),       # close
        "100.0",          # volume
        open_ms + 59_999, # close_time
        "0",              # quote_asset_volume
        "1",              # num_trades
        "50.0",           # taker_buy_base_vol
        "0",              # taker_buy_quote_vol
        "0",              # ignore
    ]


def _make_mock_client(batches: list[list]) -> MagicMock:
    """Return a mock httpx.Client context-manager that serves batches in order."""
    it = iter(batches)

    def _get(url, params=None):
        try:
            data = next(it)
        except StopIteration:
            data = []
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = data
        return mock_resp

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(side_effect=_get)
    return mock_client


# ---------------------------------------------------------------------------
# test_fetch_ohlcv_batched_stitches_correctly
# ---------------------------------------------------------------------------

def test_fetch_ohlcv_batched_stitches_correctly(monkeypatch):
    """
    Two batches are fetched, concatenated, deduplicated, and returned sorted.

    Batch 1 (most recent, 3 bars): open_times 3 000, 4 000, 5 000 ms
    Batch 2 (older,     2 bars): open_times 1 000, 2 000 ms
    Expected result: 5 bars sorted oldest → newest, no duplicates.
    """
    # Binance returns bars in ascending order within each batch
    batch1 = [_kline(3_000, 102.0), _kline(4_000, 103.0), _kline(5_000, 104.0)]
    batch2 = [_kline(1_000, 100.0), _kline(2_000, 101.0)]

    mock_client = _make_mock_client([batch1, batch2])

    # Suppress the 0.1 s sleep between batches
    monkeypatch.setattr("copilot.data.binance.time.sleep", lambda _: None)

    with patch("copilot.data.binance.httpx.Client", return_value=mock_client):
        df = fetch_ohlcv_batched("BTCUSDT", "1m", total_bars=5, batch_size=3)

    # Correct total length
    assert len(df) == 5

    # Sorted ascending
    assert df.index.is_monotonic_increasing

    # No duplicate timestamps
    assert not df.index.duplicated().any()

    # Oldest and newest bars are where we expect them
    assert df.index[0] == pd.Timestamp(1_000, unit="ms", tz="UTC")
    assert df.index[-1] == pd.Timestamp(5_000, unit="ms", tz="UTC")

    # Two API calls were made (one per batch)
    assert mock_client.get.call_count == 2

    # Second call carried an endTime param (= first bar of batch1 open_time - 1 ms)
    _, second_kwargs = mock_client.get.call_args_list[1]
    second_params = second_kwargs.get("params", {})
    assert "endTime" in second_params
    assert second_params["endTime"] == 3_000 - 1


# ---------------------------------------------------------------------------
# test_fetch_ohlcv_batched_cap
# ---------------------------------------------------------------------------

def test_fetch_ohlcv_batched_cap(capsys, monkeypatch):
    """
    When total_bars > 100 000, the function caps the request and prints a warning.
    """
    # Mock HTTP so the function exits after the first call (empty response)
    mock_client = _make_mock_client([[]])  # first (and only) batch = empty
    monkeypatch.setattr("copilot.data.binance.time.sleep", lambda _: None)

    with patch("copilot.data.binance.httpx.Client", return_value=mock_client):
        fetch_ohlcv_batched("BTCUSDT", "1m", total_bars=150_000)

    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert "100 000" in captured.out
    assert "1m" in captured.out

    # The first (only) call should request at most batch_size bars (1 500 default),
    # proving total_bars was capped before the loop started.
    first_call_params = mock_client.get.call_args_list[0][1].get("params", {})
    assert first_call_params.get("limit") == 1_500


# ===========================================================================
# BinanceSource.get_ohlc — range-based fetch (start_time / end_time)
# ===========================================================================

_1H_MS = 3_600_000  # one hour in milliseconds


def _mock_source() -> BinanceSource:
    """BinanceSource backed by a do-nothing cache so every call hits the (mocked) network."""
    cache = MagicMock(spec=OHLCCache)
    cache.get.return_value = None
    cache.get_range.return_value = None
    return BinanceSource(cache=cache)


# ---------------------------------------------------------------------------
# Test 1 — valid startTime + endTime → correct bars returned
# ---------------------------------------------------------------------------

def test_fetch_range_returns_correct_bars(monkeypatch):
    """Bars fall within [start_time, end_time] and use the canonical OHLCV schema."""
    start    = "2025-11-24T12:00:00"
    end      = "2025-11-24T14:00:00"
    start_ms = _to_ms(start)

    # Two bars: 12:00 and 13:00 — both inside the window
    raw = [_kline(start_ms + i * _1H_MS, 95_000.0 + i) for i in range(2)]
    mock_client = _make_mock_client([raw])

    monkeypatch.setattr("copilot.data.binance.time.sleep", lambda _: None)
    with patch("copilot.data.binance.httpx.Client", return_value=mock_client):
        df = _mock_source().get_ohlc("BTCUSDT", "1h", start_time=start, end_time=end)

    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is not None  # must be timezone-aware (UTC)

    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts   = pd.Timestamp(end, tz="UTC")
    assert df.index.min() >= start_ts
    assert df.index.max() <= end_ts


def test_fetch_range_passes_start_and_end_to_api(monkeypatch):
    """startTime and endTime are forwarded verbatim to the Binance API."""
    start    = "2025-11-24T12:00:00"
    end      = "2025-11-24T13:00:00"
    start_ms = _to_ms(start)
    end_ms   = _to_ms(end)

    raw = [_kline(start_ms, 95_000.0)]
    mock_client = _make_mock_client([raw])

    monkeypatch.setattr("copilot.data.binance.time.sleep", lambda _: None)
    with patch("copilot.data.binance.httpx.Client", return_value=mock_client):
        _mock_source().get_ohlc("BTCUSDT", "1h", start_time=start, end_time=end)

    params = mock_client.get.call_args_list[0][1].get("params", {})
    assert params.get("startTime") == start_ms
    assert params.get("endTime")   == end_ms


# ---------------------------------------------------------------------------
# Test 2 — start_time without end_time → ValueError
# ---------------------------------------------------------------------------

def test_fetch_range_start_only_raises():
    """Providing start_time without end_time raises ValueError.

    Open-ended queries risk fetching gigabytes of history by mistake;
    requiring an explicit end_time is a deliberate safety constraint.
    """
    with pytest.raises(ValueError, match="end_time"):
        _mock_source().get_ohlc("BTCUSDT", "1h", start_time="2025-11-24T12:00:00")


def test_fetch_range_end_only_does_not_raise(monkeypatch):
    """end_time alone (fetch most-recent bars up to a cut-off) is valid — no ValueError."""
    end      = "2025-11-24T14:00:00"
    end_ms   = _to_ms(end)

    raw = [_kline(end_ms - _1H_MS, 95_000.0)]
    mock_client = _make_mock_client([raw])

    monkeypatch.setattr("copilot.data.binance.time.sleep", lambda _: None)
    with patch("copilot.data.binance.httpx.Client", return_value=mock_client):
        df = _mock_source().get_ohlc("BTCUSDT", "1h", end_time=end)

    assert len(df) == 1


# ---------------------------------------------------------------------------
# Test 3 — time range with no data → empty canonical DataFrame
# ---------------------------------------------------------------------------

def test_fetch_range_no_data_returns_empty(monkeypatch):
    """API returns [] for an empty window → empty DataFrame with correct schema."""
    mock_client = _make_mock_client([[]])  # empty response

    monkeypatch.setattr("copilot.data.binance.time.sleep", lambda _: None)
    with patch("copilot.data.binance.httpx.Client", return_value=mock_client):
        df = _mock_source().get_ohlc(
            "BTCUSDT", "1h",
            start_time="2000-01-01T00:00:00",
            end_time="2000-01-01T02:00:00",
        )

    assert len(df) == 0
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is not None


# ---------------------------------------------------------------------------
# Test 4 — paginated range fetch → deduplicates and sorts
# ---------------------------------------------------------------------------

def test_batched_range_deduplicates_and_sorts(monkeypatch):
    """Two-page range fetch with a deliberately overlapping bar is deduplicated and sorted.

    Batch 1: 1 500 bars (full page) → triggers a second request.
    Batch 2: 3 bars where the first row duplicates the last bar of batch 1.
    Expected: 1 502 unique bars, sorted ascending, no duplicates.
    """
    start_ms = _to_ms("2025-11-24T00:00:00")
    # end_ms is set well past both pages so the boundary-trim keeps all bars
    end_ms   = start_ms + 1_600 * _1H_MS

    batch1 = [_kline(start_ms + i * _1H_MS, 95_000.0) for i in range(1_500)]
    # Intentional overlap: first bar of batch2 == last bar of batch1
    batch2 = [_kline(start_ms + i * _1H_MS, 95_000.0) for i in range(1_499, 1_502)]

    mock_client = _make_mock_client([batch1, batch2])
    monkeypatch.setattr("copilot.data.binance.time.sleep", lambda _: None)

    with patch("copilot.data.binance.httpx.Client", return_value=mock_client):
        df = _mock_source().get_ohlc(
            "BTCUSDT", "1h",
            start_time=pd.Timestamp(start_ms, unit="ms", tz="UTC").isoformat(),
            end_time=pd.Timestamp(end_ms, unit="ms", tz="UTC").isoformat(),
        )

    assert mock_client.get.call_count == 2, "expected exactly two HTTP requests"
    assert df.index.is_unique, "duplicate timestamps must be removed"
    assert df.index.is_monotonic_increasing, "bars must be sorted ascending"
    assert len(df) == 1_502  # 1 500 unique from batch1 + 2 new from batch2


def test_batched_range_trims_to_end_boundary(monkeypatch):
    """Bars whose open_time is after end_time are excluded from the result."""
    start_ms = _to_ms("2025-11-24T00:00:00")
    end_ms   = start_ms + 5 * _1H_MS  # want bars at 0h, 1h, 2h, 3h, 4h, 5h only

    # API returns 10 bars — only the first 6 are within the window
    raw = [_kline(start_ms + i * _1H_MS, 95_000.0) for i in range(10)]
    mock_client = _make_mock_client([raw])

    monkeypatch.setattr("copilot.data.binance.time.sleep", lambda _: None)
    with patch("copilot.data.binance.httpx.Client", return_value=mock_client):
        df = _mock_source().get_ohlc(
            "BTCUSDT", "1h",
            start_time=pd.Timestamp(start_ms, unit="ms", tz="UTC").isoformat(),
            end_time=pd.Timestamp(end_ms, unit="ms", tz="UTC").isoformat(),
        )

    end_ts = pd.Timestamp(end_ms, unit="ms", tz="UTC")
    assert (df.index <= end_ts).all(), "all bars must be on or before end_time"


# ---------------------------------------------------------------------------
# BatchedOHLCStore — the LTF cache the research runs depend on
# ---------------------------------------------------------------------------

_TF_MS = 60_000  # all fixtures below use 1m bars


def _fake_exchange(oldest_open_ms: int, n_bars: int, tf_ms: int = _TF_MS) -> MagicMock:
    """A mock client backed by a finite synthetic kline history.

    Honours `endTime` and `limit` the way Binance does — return the newest
    `limit` bars whose open_time is <= endTime — so backwards pagination,
    short-page-means-history-start, and the coverage arithmetic are all
    exercised for real instead of being asserted against a canned batch list.
    """
    history = [
        _kline(oldest_open_ms + i * tf_ms, 100.0 + i)
        for i in range(n_bars)
    ]

    def _get(url, params=None):
        params = params or {}
        end_time = params.get("endTime")
        limit = params["limit"]
        rows = history if end_time is None else [r for r in history if r[0] <= end_time]
        rows = rows[-limit:]
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = rows
        return resp

    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get = MagicMock(side_effect=_get)
    return client


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr("copilot.data.binance.time.sleep", lambda _: None)


@pytest.fixture
def batched_store(tmp_path):
    from copilot.data.cache import BatchedOHLCStore
    return BatchedOHLCStore(cache_dir=tmp_path / "batched")


def _fetch(client, store, total_bars, end_ms, batch_size=10):
    with patch("copilot.data.binance.httpx.Client", return_value=client):
        return fetch_ohlcv_batched(
            "BTCUSDT", "1m", total_bars=total_bars, batch_size=batch_size,
            end_ms=end_ms, store=store,
        )


def test_batched_second_identical_request_makes_no_http_calls(no_sleep, batched_store):
    """The whole point: arm 2 of a research run must not re-download arm 1's LTF frame."""
    base = 1_700_000_000_000
    client = _fake_exchange(base, 50)
    end_ms = base + 49 * _TF_MS

    first = _fetch(client, batched_store, total_bars=30, end_ms=end_ms)
    calls_after_first = client.get.call_count
    assert calls_after_first >= 3, "fixture must force real pagination"

    second = _fetch(client, batched_store, total_bars=30, end_ms=end_ms)

    assert client.get.call_count == calls_after_first, "cached window still hit the network"
    pd.testing.assert_frame_equal(first, second)
    assert len(second) == 30
    assert second.index[-1] == pd.Timestamp(end_ms, unit="ms", tz="UTC")


def test_batched_extending_forward_fetches_only_the_tail(no_sleep, batched_store):
    """A later run whose window ends an hour further on pays for the hour, not the frame."""
    base = 1_700_000_000_000
    client = _fake_exchange(base, 80)

    _fetch(client, batched_store, total_bars=40, end_ms=base + 39 * _TF_MS)
    calls_after_first = client.get.call_count

    later = _fetch(client, batched_store, total_bars=40, end_ms=base + 49 * _TF_MS)
    tail_calls = client.get.call_count - calls_after_first

    # 10 new bars at batch_size=10: one page to reach them, one to overlap the
    # bars already held. Re-fetching all 40 would take four.
    assert tail_calls <= 2, f"tail refresh took {tail_calls} pages"
    assert len(later) == 40
    assert later.index[-1] == pd.Timestamp(base + 49 * _TF_MS, unit="ms", tz="UTC")
    assert later.index[0] == pd.Timestamp(base + 10 * _TF_MS, unit="ms", tz="UTC")


def test_batched_extending_backward_fetches_only_the_head(no_sleep, batched_store):
    """Asking for more history keeps what is already held and reaches further back."""
    base = 1_700_000_000_000
    client = _fake_exchange(base, 80)
    end_ms = base + 79 * _TF_MS

    _fetch(client, batched_store, total_bars=20, end_ms=end_ms)
    calls_after_first = client.get.call_count

    deeper = _fetch(client, batched_store, total_bars=50, end_ms=end_ms)
    head_calls = client.get.call_count - calls_after_first

    assert head_calls <= 4, f"head extension took {head_calls} pages"
    assert len(deeper) == 50
    assert deeper.index[0] == pd.Timestamp(base + 30 * _TF_MS, unit="ms", tz="UTC")
    assert deeper.index[-1] == pd.Timestamp(end_ms, unit="ms", tz="UTC")
    assert deeper.index.is_monotonic_increasing
    assert not deeper.index.duplicated().any()


def test_batched_disjoint_window_replaces_instead_of_bridging(no_sleep, batched_store):
    """A window nowhere near the stored one must not drag the gap down the wire."""
    base = 1_700_000_000_000
    client = _fake_exchange(base, 2_000)

    # Recent window.
    _fetch(client, batched_store, total_bars=20, end_ms=base + 1_999 * _TF_MS)
    calls_after_first = client.get.call_count

    # A window 1 900 bars older, sharing no bar with the first.
    far = _fetch(client, batched_store, total_bars=20, end_ms=base + 49 * _TF_MS)
    second_calls = client.get.call_count - calls_after_first

    assert second_calls <= 3, (
        f"disjoint window cost {second_calls} pages — the gap was bridged"
    )
    assert len(far) == 20
    assert far.index[-1] == pd.Timestamp(base + 49 * _TF_MS, unit="ms", tz="UTC")


def test_batched_history_start_is_remembered(no_sleep, batched_store):
    """Once the series' first bar is in hand, asking for more must not re-probe for it."""
    base = 1_700_000_000_000
    client = _fake_exchange(base, 25)
    end_ms = base + 24 * _TF_MS

    first = _fetch(client, batched_store, total_bars=100, end_ms=end_ms)
    assert len(first) == 25, "fixture only has 25 bars"
    calls_after_first = client.get.call_count

    again = _fetch(client, batched_store, total_bars=100, end_ms=end_ms)

    assert client.get.call_count == calls_after_first, (
        "start-of-history was not remembered — the head was probed again"
    )
    pd.testing.assert_frame_equal(first, again)


def test_batched_use_cache_false_leaves_no_store(no_sleep, tmp_path, monkeypatch):
    """The opt-out must not write, and must still return the same window."""
    monkeypatch.setenv("TRADING_COPILOT_CACHE_DIR", str(tmp_path / "cache"))
    base = 1_700_000_000_000
    client = _fake_exchange(base, 50)
    end_ms = base + 49 * _TF_MS

    with patch("copilot.data.binance.httpx.Client", return_value=client):
        df = fetch_ohlcv_batched(
            "BTCUSDT", "1m", total_bars=30, batch_size=10,
            end_ms=end_ms, use_cache=False,
        )

    assert len(df) == 30
    assert not list((tmp_path / "cache").glob("batched_*")) if (tmp_path / "cache").exists() else True


def test_batched_returned_window_never_exceeds_end_ms(no_sleep, batched_store):
    """The store holds more than the caller asked for; the caller must not see it."""
    base = 1_700_000_000_000
    client = _fake_exchange(base, 100)

    _fetch(client, batched_store, total_bars=90, end_ms=base + 99 * _TF_MS)
    narrow = _fetch(client, batched_store, total_bars=10, end_ms=base + 49 * _TF_MS)

    assert len(narrow) == 10
    assert narrow.index[-1] == pd.Timestamp(base + 49 * _TF_MS, unit="ms", tz="UTC")
    assert narrow.index[0] == pd.Timestamp(base + 40 * _TF_MS, unit="ms", tz="UTC")
