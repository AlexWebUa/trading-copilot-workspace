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
from typing import Any, Callable

import pandas as pd

logger = logging.getLogger(__name__)

import copilot.detectors as _detectors_pkg
from copilot.data.binance import BinanceSource, fetch_multi_tf, fetch_ohlcv_with_delta

# Detectors that don't take a DataFrame (pure logic / time-based functions)
_NO_DF_TOOLS = {"check_multi_tf_alignment", "current_killzone"}

# Tools that need symbol/timeframe passed as kwargs (in addition to the df)
_PASS_META_TOOLS = {"generate_pine_script"}

# Tools that need OHLCV + delta columns (buy_vol/sell_vol/delta from klines)
_DELTA_TOOLS = {"detect_cumulative_delta", "check_cd_divergence_at_structure"}


class ToolRegistry:
    def __init__(self, data_source: BinanceSource | None = None):
        self._source = data_source or BinanceSource()
        self._schemas: list[dict] = []
        self._callables: dict[str, Callable] = {}
        self._result_cache: dict[tuple, dict] = {}
        self._discover()

    def clear_cache(self) -> None:
        """Drop all cached detector results (call between MCP requests)."""
        self._result_cache.clear()

    def _discover(self) -> None:
        for module_info in pkgutil.iter_modules(_detectors_pkg.__path__):
            mod = importlib.import_module(f"copilot.detectors.{module_info.name}")
            schema = getattr(mod, "TOOL_SCHEMA", None)
            if schema is None:
                continue
            fn_name = schema["name"]
            fn = getattr(mod, fn_name, None)
            if fn is None:
                raise RuntimeError(
                    f"Module copilot.detectors.{module_info.name} defines TOOL_SCHEMA "
                    f"with name='{fn_name}' but no function by that name was found."
                )
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

        # Build kwargs: exclude data-fetch params
        kwargs = {
            k: v for k, v in tool_input.items()
            if k not in ("symbol", "timeframe", "bars")
        }

        # Request-scoped result cache — avoids recomputing the same detector
        # within one analysis session (cleared by clear_cache() between MCP calls)
        cache_key = (tool_name, symbol, tf, bars)
        if cache_key in self._result_cache:
            return self._result_cache[cache_key]

        # Delta tools need buy_vol/sell_vol/delta columns from klines
        if tool_name in _DELTA_TOOLS:
            try:
                df = fetch_ohlcv_with_delta(symbol, tf, bars)
            except Exception as e:
                logger.exception("Delta data fetch failed for %s/%s", symbol, tf)
                return {"error": f"Delta data fetch failed for {symbol}/{tf}: {e}"}
            try:
                result = fn(df, **kwargs)
            except Exception as e:
                logger.exception("Detector %r raised", tool_name)
                return {"error": f"Detector {tool_name} raised: {e}"}
            self._result_cache[cache_key] = result
            return result

        try:
            df = self._source.get_ohlc(symbol, tf, bars)
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
        self._result_cache[cache_key] = result
        return result

    def tool_names(self) -> list[str]:
        return list(self._callables.keys())
