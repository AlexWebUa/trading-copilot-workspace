"""
Tests for the futures/spot market switch.

Motivation: spot-only listings (tokenised stocks such as QQQBUSDT, some
commodities) return `-1121 Invalid symbol` from fapi. The copilot defaulted to
futures with no way to change it, so those symbols were simply unreachable.
"""

import json

import httpx
import pytest

from copilot.data.binance import (
    DEFAULT_MARKET,
    MARKETS,
    BinanceSource,
    SymbolNotOnMarket,
    resolve_market,
)
from copilot.session import Session


class TestResolveMarket:
    def test_defaults_to_futures(self, monkeypatch):
        monkeypatch.delenv("COPILOT_MARKET", raising=False)
        assert resolve_market() == "futures"
        assert DEFAULT_MARKET == "futures"

    def test_env_var_is_honoured(self, monkeypatch):
        monkeypatch.setenv("COPILOT_MARKET", "spot")
        assert resolve_market() == "spot"

    def test_explicit_argument_beats_env(self, monkeypatch):
        monkeypatch.setenv("COPILOT_MARKET", "spot")
        assert resolve_market("futures") == "futures"

    def test_case_and_whitespace_tolerated(self, monkeypatch):
        monkeypatch.delenv("COPILOT_MARKET", raising=False)
        assert resolve_market("  SPOT ") == "spot"

    def test_unknown_market_rejected(self, monkeypatch):
        monkeypatch.delenv("COPILOT_MARKET", raising=False)
        with pytest.raises(ValueError) as exc:
            resolve_market("margin")
        assert "margin" in str(exc.value)
        for name in MARKETS:
            assert name in str(exc.value)


class TestSourceEndpoints:
    def test_futures_hits_fapi(self, monkeypatch):
        monkeypatch.delenv("COPILOT_MARKET", raising=False)
        src = BinanceSource()
        assert src.market == "futures"
        assert src.source_id == "binance_futures"
        assert src._base_url == "https://fapi.binance.com"
        assert src._endpoint == "/fapi/v1/klines"

    def test_spot_hits_api(self, monkeypatch):
        monkeypatch.setenv("COPILOT_MARKET", "spot")
        src = BinanceSource()
        assert src.market == "spot"
        assert src.source_id == "binance_spot"
        assert src._base_url == "https://api.binance.com"
        assert src._endpoint == "/api/v3/klines"

    def test_source_id_separates_the_disk_caches(self, monkeypatch):
        """Same symbol/tf on two markets are different candles — a shared cache
        key would serve futures bars for a spot request."""
        monkeypatch.delenv("COPILOT_MARKET", raising=False)
        assert BinanceSource().source_id != BinanceSource(market="spot").source_id


class _Resp:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


class _Client:
    """Stands in for httpx.Client: replays one canned response."""

    def __init__(self, resp):
        self._resp = resp
        self.calls: list[dict] = []

    def get(self, url, params=None):
        self.calls.append({"url": url, "params": params})
        return self._resp


class TestInvalidSymbolGuidance:
    def test_minus_1121_names_the_other_market(self, monkeypatch):
        monkeypatch.delenv("COPILOT_MARKET", raising=False)
        src = BinanceSource()
        client = _Client(_Resp(400, {"code": -1121, "msg": "Invalid symbol."}))

        with pytest.raises(SymbolNotOnMarket) as exc:
            src._get(client, {"symbol": "QQQBUSDT", "interval": "1h", "limit": 500})

        message = str(exc.value)
        assert "QQQBUSDT" in message
        assert "futures" in message      # where it looked
        assert "market spot" in message  # what to do about it

    def test_spot_source_points_back_at_futures(self, monkeypatch):
        monkeypatch.setenv("COPILOT_MARKET", "spot")
        src = BinanceSource()
        client = _Client(_Resp(400, {"code": -1121, "msg": "Invalid symbol."}))

        with pytest.raises(SymbolNotOnMarket) as exc:
            src._get(client, {"symbol": "SOMETHINGUSDT", "interval": "1h", "limit": 500})
        assert "market futures" in str(exc.value)

    def test_other_400s_are_not_reinterpreted(self, monkeypatch):
        """A bad interval is not a market problem — don't send the trader chasing one."""
        monkeypatch.delenv("COPILOT_MARKET", raising=False)
        src = BinanceSource()
        client = _Client(_Resp(400, {"code": -1120, "msg": "Invalid interval."}))

        with pytest.raises(httpx.HTTPStatusError):
            src._get(client, {"symbol": "BTCUSDT", "interval": "7m", "limit": 500})

    def test_success_returns_the_payload(self, monkeypatch):
        monkeypatch.delenv("COPILOT_MARKET", raising=False)
        src = BinanceSource()
        client = _Client(_Resp(200, [[1, "1", "2", "0", "1", "10", 2, "0", 1, "0", "0", "0"]]))
        assert src._get(client, {"symbol": "BTCUSDT"}) == [
            [1, "1", "2", "0", "1", "10", 2, "0", 1, "0", "0", "0"]
        ]


@pytest.fixture
def session_file():
    """The session path, already redirected into the isolated home by conftest.

    session.py resolves `_SESSION_PATH` at import time, so patching Path.home
    alone does not reach it — an unguarded save() here overwrites the trader's
    real session file (this bit once, during development of this switch).
    """
    import copilot.session

    return copilot.session._SESSION_PATH


class TestSessionPersistence:
    def test_market_defaults_to_futures(self):
        assert Session().market == "futures"

    def test_market_round_trips(self, session_file):
        Session(market="spot").save()
        assert Session.load().market == "spot"

    def test_unknown_session_keys_are_still_dropped(self, session_file):
        """Guard the load() filter that lets an older session.json keep working."""
        Session(market="spot").save()
        data = json.loads(session_file.read_text(encoding="utf-8"))
        data["some_future_field"] = 1
        session_file.write_text(json.dumps(data), encoding="utf-8")
        assert Session.load().market == "spot"

    def test_a_session_without_market_still_loads(self, session_file):
        """Sessions written before the switch existed must not break on load."""
        session_file.parent.mkdir(parents=True, exist_ok=True)
        session_file.write_text(
            json.dumps({"symbol": "ETHUSDT", "backend": "cli"}), encoding="utf-8"
        )
        loaded = Session.load()
        assert loaded.market == "futures"
        assert loaded.symbol == "ETHUSDT"


class TestMcpConfigPropagation:
    """Under the cli backend the detectors run in the MCP server two processes
    down, so the market has to travel with the spawn config."""

    def test_market_is_passed_to_the_mcp_server(self, monkeypatch):
        monkeypatch.setenv("COPILOT_MARKET", "spot")
        from copilot.llm.cli_agent import MCP_SERVER_NAME, _mcp_config

        config = json.loads(_mcp_config())
        assert config["mcpServers"][MCP_SERVER_NAME]["env"] == {"COPILOT_MARKET": "spot"}

    def test_no_env_block_when_unset(self, monkeypatch):
        monkeypatch.delenv("COPILOT_MARKET", raising=False)
        from copilot.llm.cli_agent import MCP_SERVER_NAME, _mcp_config

        config = json.loads(_mcp_config())
        assert "env" not in config["mcpServers"][MCP_SERVER_NAME]
