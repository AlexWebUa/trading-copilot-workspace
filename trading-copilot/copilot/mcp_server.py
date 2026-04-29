"""
MCP server for Claude Desktop / Cowork.

Exposes all registered detector tools over stdio transport.
The LLM (Claude Desktop) handles prompting and KB context;
this server only fetches OHLC data and dispatches detectors.

Registration in claude_desktop_config.json:
    {
      "mcpServers": {
        "trading-copilot": {
          "command": "python",
          "args": ["-m", "copilot.mcp_server"],
          "cwd": "D:\\\\Projects\\\\vibecoding\\\\trading-copilot-workspace\\\\trading-copilot",
          "env": {
            "PYTHONPATH": "D:\\\\Projects\\\\vibecoding\\\\trading-copilot-workspace\\\\trading-copilot\\\\.venv_mcp;D:\\\\Projects\\\\vibecoding\\\\trading-copilot-workspace\\\\trading-copilot"
          }
        }
      }
    }

Usage in Cowork:
  1. Create a Cowork project.
  2. Attach KB markdown files as project context files.
  3. Add system instruction (see COWORK_INSTRUCTION below).
  4. Connect this MCP server in project settings.
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure local mcp install is importable when launched by Desktop
_MCP_VENV = Path(__file__).parent.parent / ".venv_mcp"
if _MCP_VENV.exists() and str(_MCP_VENV) not in sys.path:
    sys.path.insert(0, str(_MCP_VENV))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from copilot.journal.record import TradeRecord, compute_rr, session_from_ts, parse_ts
from copilot.journal.writer import append_record
from copilot.llm.tools import ToolRegistry

# ── Suggested system instruction for Cowork projects ──────────────────────────
COWORK_INSTRUCTION = """
You are a trading co-pilot for a discretionary SMC/ICT trader.

Before any analysis:
1. Read the attached knowledge base files (Global_Rules, Entry_Models, Multi_TF_Analysis, Glossary).
2. Use the trading-copilot MCP tools to fetch real market data — never guess price levels.
3. Always call detect_market_structure on at least D1 + H4 + H1 before drawing conclusions.

Output format for every analysis:
# Analysis — {SYMBOL} · {time} Kyiv
## Bias
## Active Setup (name — LIVE / PENDING / INVALID)
### Confirmed ✅ / Pending ⏳ / Invalidates ❌
## Levels (entry / stop / TP1 / TP2)
## RR
## What I Checked (list each tool called + key finding)

Rules:
- Entry only on candle CLOSE, never intra-candle.
- Never cite a price level that didn't come from a tool result.
- No break-even targets — use nearest real liquidity pool as TP.
- If RR < 1.5R to TP1, state it explicitly.
""".strip()
# ─────────────────────────────────────────────────────────────────────────────

server = Server("trading-copilot")
_registry = ToolRegistry()

# ── save_trade tool ────────────────────────────────────────────────────────────
_SAVE_TRADE_SCHEMA: dict = {
    "name": "save_trade",
    "description": (
        "Save a completed or planned trade to the trade journal. "
        "Auto-derives session and day_of_week from ts_entry; "
        "auto-computes rr_planned from entry/sl/first TP; "
        "auto-computes pnl_r from entry/sl/exit when all three are provided."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol":          {"type": "string", "description": "e.g. BTCUSDT"},
            "direction":       {"type": "string", "enum": ["long", "short"]},
            "setup_name":      {"type": "string"},
            "account_type":    {"type": "string", "enum": ["demo", "phase1", "phase2", "live"]},
            "entry_price":     {"type": "number"},
            "sl_price":        {"type": "number"},
            "tp_prices":       {"type": "array", "items": {"type": "number"}},
            "exit_price":      {"type": "number"},
            "result":          {"type": "string", "enum": ["win", "loss", "be", "pending", "missed"]},
            "ts_entry":        {"type": "string", "description": "ISO UTC, 'YYYY-MM-DD HH:MM', or 'now'"},
            "ts_exit":         {"type": "string", "description": "ISO UTC or 'YYYY-MM-DD HH:MM'"},
            "htf_bias":        {"type": "string", "enum": ["bullish", "bearish", "ranging", ""]},
            "session":         {"type": "string", "description": "Overrides auto-derived session"},
            "killzone":        {"type": "string"},
            "tools_confirmed": {"type": "array", "items": {"type": "string"}},
            "tools_pending":   {"type": "array", "items": {"type": "string"}},
            "notes":           {"type": "string"},
            "tags":            {"type": "array", "items": {"type": "string"}},
            "pnl_r":           {"type": "number", "description": "Override auto-computed R-multiple"},
        },
        "required": ["symbol", "direction"],
    },
}


def _save_trade(arguments: dict) -> dict:
    args = dict(arguments)

    if ts_entry := args.get("ts_entry"):
        args["ts_entry"] = parse_ts(ts_entry)
    if ts_exit := args.get("ts_exit"):
        args["ts_exit"] = parse_ts(ts_exit)

    if args.get("ts_entry") and "session" not in args:
        args["session"] = session_from_ts(args["ts_entry"])
    if args.get("ts_entry") and "day_of_week" not in args:
        try:
            dt = datetime.fromisoformat(args["ts_entry"].replace("Z", "+00:00"))
            args["day_of_week"] = dt.weekday()
        except ValueError:
            pass

    entry = args.get("entry_price")
    sl = args.get("sl_price")
    tps = args.get("tp_prices", [])
    direction = args.get("direction", "")

    if entry and sl and tps and "rr_planned" not in args:
        args["rr_planned"] = compute_rr(entry, sl, tps[0], direction)

    exit_price = args.get("exit_price")
    if entry and sl and exit_price and "pnl_r" not in args:
        args["pnl_r"] = compute_rr(entry, sl, exit_price, direction)

    known = set(TradeRecord.__dataclass_fields__)
    rec = TradeRecord(**{k: v for k, v in args.items() if k in known})
    path = append_record(rec)

    return {"saved": True, "id": rec.id, "path": str(path), "record": rec.to_dict()}
# ─────────────────────────────────────────────────────────────────────────────


@server.list_tools()
async def list_tools() -> list[Tool]:
    tools = [
        Tool(name=s["name"], description=s["description"], inputSchema=s["input_schema"])
        for s in _registry._schemas
    ]
    tools.append(Tool(
        name=_SAVE_TRADE_SCHEMA["name"],
        description=_SAVE_TRADE_SCHEMA["description"],
        inputSchema=_SAVE_TRADE_SCHEMA["input_schema"],
    ))
    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "save_trade":
        result = _save_trade(arguments)
    else:
        _registry.clear_cache()
        result = _registry.dispatch(name, arguments)
    return [TextContent(type="text", text=json.dumps(result, default=str, indent=2))]


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
