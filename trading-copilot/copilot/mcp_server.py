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
from pathlib import Path

# Ensure local mcp install is importable when launched by Desktop
_MCP_VENV = Path(__file__).parent.parent / ".venv_mcp"
if _MCP_VENV.exists() and str(_MCP_VENV) not in sys.path:
    sys.path.insert(0, str(_MCP_VENV))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

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


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name=s["name"],
            description=s["description"],
            inputSchema=s["input_schema"],
        )
        for s in _registry._schemas
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    result = _registry.dispatch(name, arguments)
    return [
        TextContent(
            type="text",
            text=json.dumps(result, default=str, indent=2),
        )
    ]


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
