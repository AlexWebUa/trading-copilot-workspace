"""
Tests for copilot/data/binance.py — fetch_ohlcv_batched.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from copilot.data.binance import fetch_ohlcv_batched


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
