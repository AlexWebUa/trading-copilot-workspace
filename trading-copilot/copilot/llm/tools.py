"""
Tool registry: auto-discovers TOOL_SCHEMA + callable from each detectors/*.py module.

Each detector module exports:
  TOOL_SCHEMA : dict (Anthropic tool spec)
  <function>  : callable matching TOOL_SCHEMA["name"]

The registry wraps each callable to:
  1. Fetch OHLC data for the requested symbol/timeframe.
  2. Pass the DataFrame to the pure detector function.
  3. Return the JSON-serializable result dict.
"""

from __future__ import annotations

import importlib
import json
import logging
import pkgutil
import time
from typing import Any, Callable

import pandas as pd

logger = logging.getLogger(__name__)

import copilot.detectors as _detectors_pkg
from copilot.data.binance import BinanceSource, fetch_multi_tf, fetch_ohlcv_with_delta

# Detectors that don't take a DataFrame (pure logic / time-based functions)
_NO_DF_TOOLS = {"check_multi_tf_alignment", "current_killzone"}

# Tools that need symbol/timeframe passed as kwargs (in addition to the df)
_PASS_META_TOOLS = {"generate_pine_script"}

# Tools whose result carries a large artifact that belongs on disk rather than
# in the model's context. The detector stays pure (it just returns the text);
# this layer — which already does I/O for the OHLC fetch — persists it and
# hands back a path instead. Both frontends share the registry, so the API
# agent and the MCP/cli backend get identical behaviour.
_ARTIFACT_TOOLS = {"generate_pine_script"}

# Tools that need OHLCV + delta columns (buy_vol/sell_vol/delta from klines)
_DELTA_TOOLS = {"detect_cumulative_delta"}

# Quarantined June 2026 (Course Correction #2, PLAN.md P0-4): empirical probes
# showed these produce noise (compressions on random walks, absorption with
# below-average volume, divergence only on the current bar). Not exposed to
# the LLM until rewritten — see DETECTOR_REVIEW_2026-06-10.md.
_QUARANTINED_TOOLS = {
    "detect_compression",
    "check_absorption_at_poi",
    "check_cd_divergence_at_structure",
    # Quarantined indefinitely pending a manual redefinition by the trader —
    # the rejection-block definition needs correcting (P2-1). Hidden from the LLM
    # until then; the detector code is left untouched.
    "detect_rejection_block",
}


class ToolRegistry:
    def __init__(self, data_source: BinanceSource | None = None):
        self._source = data_source or BinanceSource()
        self._schemas: list[dict] = []
        self._callables: dict[str, Callable] = {}
        # (key) -> (monotonic_timestamp, result). See _cache_ttl for why the
        # timestamp is not optional.
        self._result_cache: dict[tuple, tuple[float, dict]] = {}
        self._discover()

    def clear_cache(self) -> None:
        """Drop all cached detector results (call between MCP requests)."""
        self._result_cache.clear()

    @staticmethod
    def _cache_ttl(tf: str | None) -> float:
        """Seconds a cached detector result stays valid, by timeframe.

        P0-10: this cache used to have no time component at all, and
        clear_cache() is never called by the MCP path — a Claude Desktop stdio
        server lives for hours, so asking about BTCUSDT 5m in the afternoon
        returned the morning's candles. On the timeframe the system exists to
        read. The disk cache below it already expires correctly; this in-memory
        layer sat in front and defeated it.

        The TTLs are imported, not re-declared, so the two layers cannot drift.
        """
        from copilot.data.cache import _DEFAULT_TTL

        if tf is None:
            # Tools that take no timeframe still depend on live data through
            # their defaults; 60 s is the tightest TTL in the table.
            return 60.0
        return float(_DEFAULT_TTL.get(tf, 300))

    def _discover(self) -> None:
        for module_info in pkgutil.iter_modules(_detectors_pkg.__path__):
            mod = importlib.import_module(f"copilot.detectors.{module_info.name}")
            schema = getattr(mod, "TOOL_SCHEMA", None)
            if schema is None:
                continue
            fn_name = schema["name"]
            if fn_name in _QUARANTINED_TOOLS:
                continue
            fn = getattr(mod, fn_name, None)
            if fn is None:
                raise RuntimeError(
                    f"Module copilot.detectors.{module_info.name} defines TOOL_SCHEMA "
                    f"with name='{fn_name}' but no function by that name was found."
                )
            # Inject time-range params into every data-fetching tool schema
            if fn_name not in _NO_DF_TOOLS:
                props = schema.setdefault("input_schema", {}).setdefault("properties", {})
                props.setdefault("start_time", {
                    "type": "string",
                    "description": (
                        "Start of historical range (ISO 8601, e.g. '2025-11-24T12:00:00'). "
                        "UTC assumed if no timezone. Overrides 'bars' when provided."
                    ),
                })
                props.setdefault("end_time", {
                    "type": "string",
                    "description": (
                        "End of historical range (ISO 8601, e.g. '2025-11-24T13:35:00'). "
                        "UTC assumed if no timezone. Defaults to most recent bar when omitted."
                    ),
                })
            self._schemas.append(schema)
            self._callables[fn_name] = fn

    def as_anthropic_tools(self) -> list[dict]:
        return [
            {"name": s["name"], "description": s["description"], "input_schema": s["input_schema"]}
            for s in self._schemas
        ]

    def dispatch(self, tool_name: str, tool_input: dict) -> dict:
        fn = self._callables.get(tool_name)
        if fn is None:
            return {"error": f"Unknown tool: {tool_name}"}

        if tool_name in _NO_DF_TOOLS:
            # Pass kwargs directly (no DataFrame)
            return fn(**tool_input)

        symbol = tool_input.get("symbol", "BTCUSDT").upper()
        tf = tool_input.get("timeframe", "1h")
        bars = tool_input.get("bars", 500)
        start_time = tool_input.get("start_time")
        end_time = tool_input.get("end_time")

        # Build kwargs: exclude data-fetch params
        _FETCH_PARAMS = {"symbol", "timeframe", "bars", "start_time", "end_time"}
        kwargs = {k: v for k, v in tool_input.items() if k not in _FETCH_PARAMS}

        # Request-scoped result cache — avoids recomputing the same detector
        # within one analysis session (cleared by clear_cache() between MCP calls).
        #
        # P0-9: the key includes the detector kwargs. 15 of 16 exposed tools take
        # params, so a key of (tool, symbol, tf, bars, range) made a re-probe with
        # different params return the FIRST answer — silently, with genuine-looking
        # numbers that _verify_report_numbers cannot flag. Same bug class as the
        # P0-2 HTF cache-key fix.
        cache_key = (
            tool_name, symbol, tf, bars, start_time, end_time,
            json.dumps(kwargs, sort_keys=True, default=str),
        )
        cached = self._result_cache.get(cache_key)
        if cached is not None:
            cached_at, cached_result = cached
            if time.monotonic() - cached_at < self._cache_ttl(tf):
                return cached_result
            del self._result_cache[cache_key]

        # Delta tools need buy_vol/sell_vol/delta columns from klines
        if tool_name in _DELTA_TOOLS:
            try:
                # P0-6: go through the injected source (and its cache) when
                # it supports delta; module-level fetch is the fallback.
                if hasattr(self._source, "get_ohlc_with_delta"):
                    df = self._source.get_ohlc_with_delta(symbol, tf, bars)
                else:
                    df = fetch_ohlcv_with_delta(symbol, tf, bars)
            except Exception as e:
                logger.exception("Delta data fetch failed for %s/%s", symbol, tf)
                return {"error": f"Delta data fetch failed for {symbol}/{tf}: {e}"}
            try:
                result = fn(df, **kwargs)
            except Exception as e:
                logger.exception("Detector %r raised", tool_name)
                return {"error": f"Detector {tool_name} raised: {e}"}
            self._result_cache[cache_key] = (time.monotonic(), result)
            return result

        try:
            df = self._source.get_ohlc(symbol, tf, bars, start_time=start_time, end_time=end_time)
        except Exception as e:
            logger.exception("Data fetch failed for %s/%s", symbol, tf)
            return {"error": f"Data fetch failed for {symbol}/{tf}: {e}"}

        # Some tools (e.g. generate_pine_script) need symbol/tf for output labelling
        if tool_name in _PASS_META_TOOLS:
            kwargs["symbol"] = symbol
            kwargs["timeframe"] = tf

        try:
            result = fn(df, **kwargs)
        except Exception as e:
            logger.exception("Detector %r raised", tool_name)
            return {"error": f"Detector {tool_name} raised: {e}"}

        if tool_name in _ARTIFACT_TOOLS:
            result = _persist_artifact(tool_name, result, symbol, tf)

        self._result_cache[cache_key] = (time.monotonic(), result)
        return result

    def tool_names(self) -> list[str]:
        return list(self._callables.keys())


def _persist_artifact(tool_name: str, result: dict, symbol: str, tf: str) -> dict:
    """Write a tool's bulky artifact to disk, replacing it with a path.

    `generate_pine_script` returns several hundred lines of Pine. Feeding that
    back through the tool result would burn context on every analysis and drag
    every drawn price level into the transcript. The detector stays pure; the
    file lands in ~/.trading-copilot/pine/ and the model gets `pine_file`.

    A failed write is not fatal: the script stays in the result and the model can
    still print it, which beats losing the analysis over a disk error.
    """
    if tool_name != "generate_pine_script":
        return result
    script = result.get("pine_script")
    if not isinstance(script, str) or not script:
        return result

    from copilot.pine.store import save_pine

    out = dict(result)
    try:
        out["pine_file"] = str(save_pine(symbol, tf, script))
        out.pop("pine_script", None)
    except Exception as e:
        logger.exception("Failed to save Pine artifact for %s/%s", symbol, tf)
        out["pine_file_error"] = str(e)
    return out
