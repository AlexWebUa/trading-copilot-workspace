"""
System prompt builder. Assembles:
  1. Role & instructions
  2. Always-injected KB notes (cached across the session)
  3. Query-triggered KB notes (per turn)
  4. Session context (symbol, current time, killzone state)
  5. Output format specification
"""

from __future__ import annotations

from copilot.detectors.sessions import current_killzone
from copilot.kb.loader import Note

_ROLE = """You are a trading co-pilot for a discretionary SMC/ICT trader.
Your job is to use the available detector tools to analyze real OHLC market data,
then produce a structured analysis report grounded in the trading rules from the knowledge base below.

CRITICAL RULES:
- Never invent price levels. Every level you cite in the report must come from a tool result.
- Always call detect_market_structure on at least 2 timeframes before drawing conclusions.
- Entry confirmation requires candle CLOSE (never intra-candle).
- No break-even targets — cite nearest real liquidity pool as TP.
- If a setup has <1.5R to first TP, say so explicitly.
- If outside OTT window (09:00–17:00 Kyiv), note it in the report.
- If structure is unclear on any timeframe, state "insufficient structure" — do not guess.
"""

_OUTPUT_FORMAT = """
## REQUIRED OUTPUT FORMAT (final response only — not during tool calls)

Use exactly this markdown structure:

# Analysis — {SYMBOL} · {DATETIME} Kyiv

## Bias
- **HTF (timeframe):** [bullish/bearish/ranging] — [reason from tool output]
- **MTF (timeframe):** [state], [aligned/desync]
- **LTF (timeframe):** [state] — [role: pullback/continuation]

## Active Setup
**[Setup name or "No setup — conditions not met"]** — [LIVE / PENDING / INVALID]

### Confirmed ✅
- [bullet per confirmed condition, with price from tool result]

### Pending ⏳
- [bullet per unconfirmed condition still needed]

### Invalidates ❌
- [bullet per condition that would kill the setup]

## Levels
| Type | Price | Note |
|---|---|---|
| Entry | [price] | [trigger condition] |
| Stop | [price] | [structural reason] |
| TP1 | [price] | [liquidity pool or FVG label] |
| TP2 | [price] | [secondary target if exists] |

## RR
[X.XR to TP1, Y.YR to TP2]. [Comment on whether threshold ≥1.5R is met.]

## What I Checked
- [list each tool called and its key finding]
"""


def build_system_prompt(
    core_notes: list[Note],
    query_notes: list[Note],
    symbol: str,
    session_context: dict | None = None,
) -> list[dict]:
    """
    Returns the system prompt as an Anthropic messages-API system list
    with cache_control on the stable core section.
    """
    ctx = session_context or current_killzone()

    # Core section: stable across session → cache it
    core_kb_text = "\n\n".join(n.as_context_block() for n in core_notes)
    core_content = (
        f"{_ROLE}\n\n"
        f"# Your Trading Rules (Knowledge Base)\n\n{core_kb_text}\n\n"
        f"{_OUTPUT_FORMAT}"
    )

    system_blocks: list[dict] = [
        {
            "type": "text",
            "text": core_content,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    # Query-specific notes: added per turn, not cached
    if query_notes:
        extra_kb = "\n\n".join(n.as_context_block() for n in query_notes)
        system_blocks.append({
            "type": "text",
            "text": f"# Additional Context (Setup-Specific)\n\n{extra_kb}",
        })

    # Session context: symbol, time, killzone
    kz = ctx.get("active_killzone") or ctx.get("next_killzone", "none")
    system_blocks.append({
        "type": "text",
        "text": (
            f"# Session Context\n"
            f"Symbol: {symbol}\n"
            f"Kyiv time: {ctx.get('kyiv_time', '?')} ({ctx.get('weekday', '?')})\n"
            f"OTT window active: {ctx.get('in_ott_window', False)}\n"
            f"Killzone: {kz}\n"
            f"Friday (TGIF watch): {ctx.get('is_friday', False)}\n"
        ),
    })

    return system_blocks
