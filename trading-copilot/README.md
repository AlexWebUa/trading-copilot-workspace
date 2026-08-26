# Trading Co-Pilot

A terminal co-pilot for a discretionary SMC/ICT trader. Claude reads the trader's Obsidian knowledge base
as context, then calls algorithmic price detectors as tools over real Binance OHLC data, and produces a
structured market analysis. **Analysis only — it places no orders.** The trader reads the output and makes
the call.

Two frontends share one detector registry:
- **CLI REPL** — multi-turn chat in the terminal, over either LLM backend (below).
- **MCP server** — the same detectors as tools inside Claude Desktop / Cowork.

## Quick start

```bash
cd trading-copilot-workspace/trading-copilot
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env            # add ANTHROPIC_API_KEY=sk-ant-...

python -m copilot --symbol BTCUSDT --verbose     # REPL
./run_mcp.sh                                      # MCP server (stdio; Windows: run_mcp.bat)
python -m pytest                                  # tests (no network)
```

Scripts require the venv (system `python3` lacks pandas etc.). Backtests and stats run without an API key:
`backtest --rule <name> --tf 1h --bars 1000 [--split 0.7]`, `compare --all --wf`, `stats --group tool`.

## Two LLM backends

The REPL can reach Claude two ways — same prompts, same detectors, same report, different bill.

| | `--backend api` (default) | `--backend cli` |
|---|---|---|
| Path | Anthropic Messages API, loop in `llm/agent.py` | `claude -p` headless, loop inside Claude Code |
| Detectors reach the model via | `ToolRegistry` dispatch | the project's own MCP server |
| Billing | usage-based API credits | Claude subscription plan limits |
| Needs | `ANTHROPIC_API_KEY` | the `claude` CLI on PATH, logged in |

```bash
python -m copilot --backend cli          # or: export COPILOT_BACKEND=cli
                                         # or: the `backend cli` REPL command
```

The CLI backend drives `claude -p` and exposes the detectors through
`copilot/mcp_server.py`, because Claude Code runs its own agent loop and can only
reach Python tools over MCP. It strips `ANTHROPIC_API_KEY` from the subprocess so
Claude Code authenticates with the subscription instead of falling back to API
billing. Traces, the anti-hallucination check, the saved report and the
cross-run state snapshot all behave identically; prompt-cache breakpoints and the
`MAX_TURNS` ceiling are not controllable (a wall-clock timeout replaces the
latter). Env knobs: `COPILOT_BACKEND`, `COPILOT_CLAUDE_BIN`, `COPILOT_CLI_MODEL`,
`COPILOT_CLI_TIMEOUT`, `COPILOT_CLI_WORKSPACE`.

## Futures or spot

Detectors read Binance USD-M perpetuals by default. Spot-only listings — tokenised stocks
(`QQQBUSDT`) and part of the commodities section — return `-1121 Invalid symbol` from `fapi`,
so the market is switchable:

```bash
python -m copilot --market spot          # or: export COPILOT_MARKET=spot
                                         # or: the `market spot` REPL command
```

Precedence is `--market` > `COPILOT_MARKET` > the persisted session > `futures`; the choice is
saved between runs and travels to the MCP server the cli backend spawns. The two markets cache
separately (`binance_futures` / `binance_spot`), because the same symbol on each is a different
order book — `XAUTUSDT` closed at 4579.93 on futures and 4582.46 on spot at the same minute.
A symbol that is not on the selected market now says which one to try instead of returning a
bare HTTP 400.

## Status

Phases 1–6 are built; a June 2026 audit found core detectors and the backtest engine broken and fixed the
source-data/evidence-integrity issues (P0) and test integrity (P1-1). Several detectors are still being
repaired and **no profitable edge has been demonstrated yet** — see [PLAN.md](PLAN.md) and
[PROGRESS.md](PROGRESS.md).

## Documentation

| Doc | Contents |
|---|---|
| [PLAN.md](PLAN.md) | Current roadmap and step state — the single source of "what's next" |
| [PROGRESS.md](PROGRESS.md) | What's built and how trustworthy each piece is |
| [CLAUDE.md](CLAUDE.md) | Orientation for Claude Code working in this repo |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Module map, data layer, detector contracts, LLM loop, output format |
| [docs/CONVENTIONS.md](docs/CONVENTIONS.md) | Engineering rules: knowledge hierarchy, test standards, coding rules, R1–R5 |
| [docs/AUDIT_HISTORY.md](docs/AUDIT_HISTORY.md) | The two 2026 correction cycles and why |
| [docs/RESEARCH_PROTOCOL.md](docs/RESEARCH_PROTOCOL.md), [docs/TRADING_RULES_DRAFT.md](docs/TRADING_RULES_DRAFT.md) | The trader's methodology the system encodes |
| [REVIEW_2026-06-10.md](REVIEW_2026-06-10.md), [DETECTOR_REVIEW_2026-06-10.md](DETECTOR_REVIEW_2026-06-10.md), [REBASELINE_2026-06-10.md](REBASELINE_2026-06-10.md) | Raw audit reports |
