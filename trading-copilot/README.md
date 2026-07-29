# Trading Co-Pilot

A terminal co-pilot for a discretionary SMC/ICT trader. Claude reads the trader's Obsidian knowledge base
as context, then calls algorithmic price detectors as tools over real Binance OHLC data, and produces a
structured market analysis. **Analysis only — it places no orders.** The trader reads the output and makes
the call.

Two frontends share one detector registry:
- **CLI REPL** — multi-turn chat in the terminal (Anthropic SDK).
- **MCP server** — the same detectors as tools inside Claude Desktop / Cowork.

## Quick start

```bash
cd trading-copilot-workspace/trading-copilot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # add ANTHROPIC_API_KEY=sk-ant-...

python -m copilot --symbol BTCUSDT --verbose     # REPL
./run_mcp.sh                                      # MCP server (stdio)
python -m pytest                                  # tests (no network)
```

Scripts require the venv (system `python3` lacks pandas etc.). Backtests and stats run without an API key:
`backtest --rule <name> --tf 1h --bars 1000 [--split 0.7]`, `compare --all --wf`, `stats --group tool`.

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
