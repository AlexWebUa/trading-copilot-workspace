# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python "trading co-pilot": Claude reads a discretionary SMC/ICT trader's Obsidian knowledge base
(`../knowledge_base/`, read-only) as narrative context, then calls **algorithmic price detectors as
tools** over real Binance OHLC data, and emits a structured market analysis. Analysis only — no order
placement. Two frontends share one detector registry: a terminal **REPL** (`copilot/cli.py`, Anthropic
SDK) and an **MCP server** (`copilot/mcp_server.py`, Claude Desktop / Cowork).

## ⚠️ Project status — read before trusting any detector or backtest number

The codebase passed two audits (May & June 2026) that found core detectors and the backtest engine
broken. **[PLAN.md](PLAN.md)** is the roadmap/state; **[PROGRESS.md](PROGRESS.md)** is the current
built-state snapshot; **[docs/AUDIT_HISTORY.md](docs/AUDIT_HISTORY.md)** explains why.

- The P0 remediation (P0-1…P0-7) is **done**: forming-bar drop, backtest look-ahead fixes,
  `smartmoneyconcepts` rewrap, broken-tool quarantine, CD rewrite, honest cost model, re-baseline.
  The re-baseline (`REBASELINE_2026-06-10.md`) found **no rule has a positive edge** under honest
  costs — earlier positive backtests were look-ahead + one-sided-fee artifacts.
- **P1-1/P1-2/P1-3 and P2-1/P2-2 are done.** `tests/test_probe_regression.py` encodes all 20 June
  probes; the vacuous `test_detectors_liquidity.py` was deleted; `agent.py` keys tool results by
  `(name, symbol, tf)` and runs the anti-hallucination check; `prompts.py` enforces the HTF-POI hard
  gate + conflict hierarchy MS > sweep > OB/FVG > orderflow + position management. The detector
  repairs flipped every probe `xfail` except the quarantined tools: the suite is now **351 pass +
  3 xfail** (compression, cd_absorption, rejection_block — all quarantined, all still broken by
  design). Still pending: P1-4 probability assessment.
- **⚠️ P0b (P0-8…P0-11) is the current frontier and gates everything.** A 2026-07-29 review found
  three verified evidence-integrity bugs of the same class as P0-1…P0-7 — see [PLAN.md](PLAN.md).
  Until P0-8 lands and the re-baseline is re-run, **backtest numbers are still not trustworthy**:
  the engine never scans the entry bar for SL/TP, so every trade gets one bar of stop immunity and
  trades left open at end-of-data are dropped from the stats entirely. The registry result cache
  also ignores detector kwargs, so re-probing a detector with different params silently returns the
  previous answer. No feature work (P3+) until P0b–P1 land.
- Detectors still flagged unreliable/quarantined live in `DETECTOR_REVIEW_2026-06-10.md` and
  `_QUARANTINED_TOOLS` in `copilot/llm/tools.py`. Don't build on them without checking that doc first.

## Commands

Scripts need the project venv (system `python3` lacks pandas/etc.). Use `.venv/bin/python` directly or
`source .venv/bin/activate` first.

```bash
# Tests (354 collected: 351 pass + 3 xfail) — all programmatic fixtures, no network
.venv/bin/python -m pytest                                  # full suite
.venv/bin/python -m pytest tests/test_probe_regression.py   # the probe-derived regression suite
.venv/bin/python -m pytest tests/test_detectors_smc_rewrap.py -k bos -q   # one test by name

# Run the REPL (needs ANTHROPIC_API_KEY in .env)
.venv/bin/python -m copilot --symbol BTCUSDT --verbose

# MCP server (stdio) — what Claude Desktop launches
./run_mcp.sh

# Empirical detector probes — human-readable PASS/FAIL exploration. Now encoded as
# tests/test_probe_regression.py (P1-1); keep these for ad-hoc fixture experiments.
.venv/bin/python probes/probe_detectors.py

# Per-detector Pine Script debug output → pine_debug/ (gitignored), overlay on TradingView
.venv/bin/python scripts/debug_detectors.py --help

# Re-run the trustworthy backtest baseline
.venv/bin/python scripts/rebaseline.py

# Backtests / stats are also REPL commands (no API key needed for these):
#   backtest --rule <name> --tf 1h --bars 1000 [--split 0.7]   |  backtest --list-rules
#   compare --all --wf  |  stats --group tool
```

There is no separate lint/format config — match surrounding style.

## Architecture

Data flows **detector (pure) → registry (fetch+dispatch) → agent loop / MCP server (LLM frontend)**.

### Detector contract (the core abstraction)
Each `copilot/detectors/<concept>.py` is **one concept, one pure function + a co-located `TOOL_SCHEMA`
dict** (Anthropic tool spec; the function name must equal `TOOL_SCHEMA["name"]`). Input: the canonical
OHLCV DataFrame + params. Output: a JSON-serializable dict. No I/O, no hidden state. Adding a detector
is a **one-file change** — no registry edits.

- **Canonical DataFrame** (`data/normalize.py`): DatetimeIndex UTC named `ts`, float64 columns
  `open, high, low, close, volume` (delta tools add `buy_vol, sell_vol, delta`). Everything — detectors,
  fixtures, backtest — uses exactly this shape.
- **`smc_lib.py`** wraps the `smartmoneyconcepts` library, the declared algorithmic ground truth for
  swings and BOS/CHoCH. Detectors are thin adapters over it, **except** where the library is empirically
  wrong: `detect_order_block` keeps a hand-rolled swing-break scan over RAW confirmed swings because
  `smc.ob` inherits root-cause R1 (swing dedup erases the broken swing) — see the module docstring.

### Tool registry & dispatch (`llm/tools.py`)
`ToolRegistry` auto-discovers `TOOL_SCHEMA` from every `detectors/*.py` via `pkgutil`. Dispatch fetches
OHLC for the requested `symbol`/`timeframe`/`bars` (or `start_time`/`end_time` range), calls the pure
function, caches the result request-scoped. Special-case sets at the top of the file:
- `_NO_DF_TOOLS` — pure logic, no DataFrame (`check_multi_tf_alignment`, `current_killzone`).
- `_DELTA_TOOLS` — need `buy_vol/sell_vol/delta` (`detect_cumulative_delta`), fetched via the delta path.
- `_PASS_META_TOOLS` — need `symbol`/`tf` for labels (`generate_pine_script`).
- `_QUARANTINED_TOOLS` — **excluded from discovery**; noise-producing detectors hidden from the LLM
  until rewritten. The same registry feeds both the SDK agent and the MCP server, so quarantine is global.

### Two frontends, one registry
- `llm/agent.py` `TradingAgent.analyze()` — multi-turn tool-use loop (`MAX_TURNS=12`), KB-injected
  system prompt with ephemeral prompt caching, writes a report (`llm/report.py`), a per-call JSONL
  trace (`llm/trace.py`), and a state snapshot whose diff is injected into the next run (`llm/state.py`).
  Tool results are keyed by `(name, symbol, tf)` via `_result_key` so multi-TF calls don't overwrite each
  other; on the final turn `_verify_report_numbers` flags any price-like report value absent from every
  tool result (loud stderr warning + trace record — heuristic, non-fatal).
- `mcp_server.py` — exposes the same schemas over stdio plus a `save_trade` tool; result cache persists
  for the process lifetime (not cleared per call).

### Supporting modules
- `data/binance.py` — USD-M futures (`fapi.binance.com`) by default, spot fallback; `data/cache.py`
  is a TTL parquet disk cache; `data/base.py` is the `DataSource` protocol for future instruments.
- `kb/` — `loader.py` parses Obsidian markdown+frontmatter; `selector.py` does two-tier injection
  (always-core notes from `config.toml` + keyword-triggered per query).
- `journal/` — append-only SQLite (WAL) at `~/.trading-copilot/journal/journal.db`; `record.py`
  `TradeRecord` is the schema for both live trades and backtest entries (`record_type`).
- `backtest/` — `engine.py` bar-by-bar state machine (IDLE→SIGNAL→LTF_SCAN→IN_TRADE→IN_TRADE_P2),
  `rules.py`/`rules_orderflow.py` declarative `SetupRule`s, writes results to the journal.
- `stats/` — winrate / profit factor / expectancy aggregation + tool-effectiveness Δwinrate ranking.

## Conventions (summary — full rules in [docs/CONVENTIONS.md](docs/CONVENTIONS.md))

- **Never analyze the forming candle.** `normalize_binance(..., include_forming=False)` drops the last
  kline when `close_time > now`. Historical ranges are unaffected.
- **Detector algorithms come from verified implementations**, not KB prose: `smartmoneyconcepts` first,
  high-rated TradingView Pine Scripts for visual ground truth, KB only for ICT terminology/interpretation.
- **Tests assert known behavior on explicitly constructed fixtures**, never schema shape.
  `assert "x" in result` / `assert total >= 0` are **forbidden**. Fixtures are built programmatically
  in `tests/conftest.py` — `tests/fixtures/` is empty; there are no parquet files.
- **Probes are the regression suite**: every bug found by `probes/*.py` is a test in
  `tests/test_probe_regression.py`. A bug whose fix hasn't landed is `xfail(strict=True)` with a `reason`
  citing the PLAN item — it goes green (XPASS, failing the suite) the moment the fix lands, forcing the
  marker's removal. Use the same pattern for any new known-broken-detector test.
- Internal computation uses integer DataFrame-position `idx`, not timestamps; ISO 8601 strings only in
  output. ATR is per-bar true-range (`smc_lib.true_range_atr`) — never a static scalar in a loop.
  Swing detection deduplicates to strict H-L-H-L alternation, but break detection must consume swings
  **chronologically** so a structurally-broken swing is never erased (root cause R1).
- **Fail soft** (`{"status": "none"}` / `count: 0`, never raise for "nothing found"); **compact output**
  (3–10 most recent objects).

## Key docs

- [PLAN.md](PLAN.md) — roadmap and step state (the single source of "what's next").
- [PROGRESS.md](PROGRESS.md) — what's built and how trustworthy each piece is.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — module map, data layer, detector contracts, LLM loop, output format.
- [docs/CONVENTIONS.md](docs/CONVENTIONS.md) — full engineering rules + root causes R1–R5.
- [docs/AUDIT_HISTORY.md](docs/AUDIT_HISTORY.md) — the two 2026 correction cycles; links the raw audit reports.
- [DETECTOR_REVIEW_2026-06-10.md](DETECTOR_REVIEW_2026-06-10.md) — per-tool verdicts (sound / degraded / broken).
- [docs/RESEARCH_PROTOCOL.md](docs/RESEARCH_PROTOCOL.md), [docs/TRADING_RULES_DRAFT.md](docs/TRADING_RULES_DRAFT.md) — the trader's methodology.
