# Architecture & Design

How the trading co-pilot is structured and why. For the current roadmap see [../PLAN.md](../PLAN.md);
for engineering rules see [CONVENTIONS.md](CONVENTIONS.md); for what is actually built see
[../PROGRESS.md](../PROGRESS.md).

## Context

The user is a discretionary SMC/ICT trader with a complete, structured Obsidian KB at
`../knowledge_base/`. The system lets **Claude (via the Anthropic SDK) read the KB as narrative
context, then call algorithmic detectors over OHLC data as tools** to produce a structured market
analysis the trader acts on manually.

**Why this shape.** The KB encodes the "what to think" (concepts, setups, entry models, global rules).
What an LLM cannot do alone is reliably *measure* things on a chart — fractal sweeps, FVG fill depth, OB
mitigation state, multi-TF confluence. Detectors close that gap by returning **compact, self-describing
JSON** the LLM can reason over without hallucinating candle positions.

**Decisions locked at kickoff:**
- LLM backend: Anthropic SDK primary (Sonnet 4.6 default). Multi-LLM abstraction deferred.
- Instruments v1: **crypto only (BTC, ETH)** via Binance public REST. Data layer kept pluggable so
  XAU/USD, EUR/USD, GER40/EU50, NAS100/SP500 can be added later.
- Interface: **interactive REPL/chat** in the terminal, plus an MCP server for Claude Desktop / Cowork.

**Hard constraints:**
- No order placement. Analysis only.
- Detectors pure-functional, unit-testable against fixture OHLC (no live API dependency in tests).
- Multi-TF is non-negotiable: D1 → H4 → H1 → M15 → M3/M1 is how the user thinks; the system mirrors it.
- Session-awareness: OTT window 09:00–17:00 Kyiv, killzones at 09:00 / 15:00 / 17:00 Kyiv.

## Module map

```
copilot/
├── cli.py / __main__.py     REPL entry point
├── session.py               REPL state (symbol, model, transcript)
├── mcp_server.py            MCP stdio server (Claude Desktop / Cowork)
│
├── data/
│   ├── base.py              DataSource protocol + tf validation
│   ├── binance.py           USD-M futures fetcher (fapi.binance.com), spot fallback
│   ├── cache.py             parquet disk cache, TTL per TF
│   └── normalize.py         canonical OHLCV schema; drops the forming candle
│
├── detectors/               one concept = one file = one pure function + TOOL_SCHEMA
│   ├── smc_lib.py           adapter over the smartmoneyconcepts library (ground truth)
│   ├── utils.py             shared ATR / array / fvg-zone helpers
│   ├── market_structure.py, bos.py, fractals.py
│   ├── fvg.py, ifvg.py, order_block.py, breaker_block.py, mitigation_block.py,
│   │   rejection_block.py, sponsored_candle.py, liquidity.py, fib_zones.py, compression.py
│   ├── cumulative_delta.py, volume_profile.py, orderflow_composite.py,
│   │   absorption_poi.py, cd_divergence_structure.py
│   ├── multi_tf.py          HTF/LTF reconciliation (no DataFrame)
│   ├── sessions.py          killzone / OTT helpers (no DataFrame)
│   └── pine_script.py       charts the detectors the analysis deemed significant (thin wrapper
│                            over pine/) → TradingView v5 overlay
│
├── pine/
│   ├── emitters.py          per-detector Pine bodies + EmitContext (shared with debug_detectors.py)
│   ├── runners.py           how each detector is invoked to produce those bodies
│   ├── overlay.py           OVERLAY_LAYERS + build_overlay: chosen layers → one toggle-able indicator
│   └── store.py             writes ~/.trading-copilot/pine/{SYMBOL}_{tf}_{ts}.pine
│
├── llm/
│   ├── tools.py             ToolRegistry: auto-discovers TOOL_SCHEMA, fetches data, dispatches
│   ├── agent.py             multi-turn tool-use loop + prompt caching
│   ├── prompts.py           system prompt builder (KB + session + previous-analysis diff)
│   ├── report.py            saves reports to ~/.trading-copilot/reports/
│   ├── trace.py             one JSONL record per tool call
│   └── state.py             per-session detector snapshot + diff injection
│
├── kb/                      loader.py (frontmatter parse) + selector.py (two-tier injection)
├── journal/                SQLite (WAL) trade journal: record / db / writer / reader
├── backtest/               engine / rules / rules_orderflow / simulate / report / compare
└── stats/                  aggregator (winrate/PF/expectancy/tool-effectiveness) + cli
```

Data flows **detector (pure) → registry (fetch + dispatch) → agent loop / MCP server (LLM frontend)**.
`detectors/` and `data/` are the core; everything else is thin glue.

## Data layer

### Canonical schema (`data/normalize.py`)
Every detector consumes exactly one shape: `DatetimeIndex` UTC named `ts`, float64 columns
`open, high, low, close, volume`. Delta tools add `buy_vol, sell_vol, delta` (from the kline
`taker_buy_base_vol` — exact candle-level delta, no tick data needed). Fixtures use the same schema.

**The forming candle is dropped.** `normalize_binance(..., include_forming=False)` removes the last kline
when its `close_time > now`. Analyzing an in-progress bar repaints and violates the "entry only on candle
CLOSE" rule. Historical ranges are unaffected (their last bar is already closed).

### Fetch & cache (`data/binance.py`, `data/cache.py`)
USD-M perpetual futures (`fapi.binance.com`) by default — what discretionary traders actually trade.
Spot (`api.binance.com`) is a first-class alternative, not a fallback: tokenised stocks and part of the
commodities section list on spot only, and futures answers `-1121 Invalid symbol` for them. `resolve_market()`
picks between the two (explicit arg > `COPILOT_MARKET` > `futures`); `--market` / the `market` REPL command
exports the env var so the choice reaches both the in-process registry and the MCP server the cli backend
spawns. `_get()` translates a `-1121` into `SymbolNotOnMarket` naming the market to try instead.

Up to 1500 bars/request; `_fetch_range` paginates. Parquet disk cache keyed by
`(source, symbol, tf, bars)` or `(…, start, end)`, TTL per TF (1m/3m 60s, 15m/1h 5min, 4h/1d 1h) — the
`source` term is `binance_futures` / `binance_spot`, so the same symbol on two markets never shares a
cache entry. `fetch_multi_tf` returns `{tf: DataFrame}`. Delta has its own cache namespace so column
sets never collide, and follows the source's market (a spot backtest no longer pulls futures delta).

### Pluggability (`data/base.py`)
`DataSource` is a Protocol (`get_ohlc`, `supports`). Binance is the first impl; adding a source = new file
implementing the protocol + a registry line. Detectors never change.

## Detector library

### Design principles
1. **Pure function.** Input: canonical DataFrame + params. Output: JSON-serializable dict. No I/O, no state.
2. **Compact output.** Return the 3–10 most recent / relevant objects, not every historical match.
3. **Self-describing fields** (`is_mitigated`, `fill_percentage` — not `mit`, `fp`).
4. **Rounded prices**, ISO 8601 UTC timestamp strings in output (pandas Timestamps don't round-trip
   through Anthropic tool results).
5. **Fail soft.** Empty → `{"status": "none", ...}` / `count: 0`. Never raise for "nothing found".

### Algorithmic ground truth
`smc_lib.py` wraps the `smartmoneyconcepts` library (a real dependency, not a reference to reimplement)
for swings and BOS/CHoCH. Detectors are thin adapters converting its output to our JSON contracts —
**except** where the library is empirically wrong: `detect_order_block` keeps a hand-rolled swing-break
scan over RAW confirmed swings because `smc.ob` inherits root-cause R1. Custom code only for concepts the
library lacks (killzones, sponsored candle, multi-TF, composites). See [CONVENTIONS.md](CONVENTIONS.md)
for the knowledge hierarchy and R1–R5.

### Tiers
- **Tier A** (core market picture): market_structure, bos, fvg, order_block, liquidity, fib_zones,
  fractals, multi_tf.
- **Tier B**: ifvg, breaker_block, mitigation_block, rejection_block, sponsored_candle, compression,
  current_killzone.
- **Orderflow**: cumulative_delta, volume_profile, + composites (ob_in_hvn, poc_location, price_in_lvn,
  absorption, cd_divergence_at_structure). The composites have **no `TOOL_SCHEMA`** and are **not exposed
  to the LLM** — they exist only in the backtest registry (`backtest/rules.py`); the agent reads the same
  context from `detect_volume_profile` fields directly. `absorption`/`cd_divergence_at_structure` are also
  quarantined.
- **Tier C (deferred)**: footprint imbalances, VWAP/TPO — need L2/tick data unavailable on public REST.

Per-tool correctness verdicts live in [DETECTOR_REVIEW_2026-06-10.md](../DETECTOR_REVIEW_2026-06-10.md);
which tools are exposed vs quarantined is enforced by `_QUARANTINED_TOOLS` in `llm/tools.py`.

### Edge cases (codified as tests)
- Fewer bars than lookback → `{"status": "insufficient_data", "needed": N, "got": M}`.
- All-same-price bars (halted market) → skip, don't divide by zero.
- Wrong TF string → raise early with available TFs listed.

## LLM integration layer

### Tool schema generation & registry (`llm/tools.py`)
Each detector co-locates a `TOOL_SCHEMA` dict (Anthropic tool spec) whose `name` equals the function name.
`ToolRegistry` auto-discovers them via `pkgutil` — adding a detector is a one-file change, no registry
edits. Tool descriptions are phrased "Use when you need to […]" because the description is what Claude
reads to decide when to call the tool. Dispatch fetches OHLC for the requested `symbol`/`timeframe`/
`bars` (or `start_time`/`end_time`), calls the pure function, and caches the result request-scoped.
Special-case sets: `_NO_DF_TOOLS` (no DataFrame), `_DELTA_TOOLS` (need delta columns), `_PASS_META_TOOLS`
(need symbol/tf for labels), `_QUARANTINED_TOOLS` (excluded from discovery). The same registry feeds both
the SDK agent and the MCP server, so quarantine is global.

### Agent loop (`llm/agent.py`)
Standard Anthropic tool-use loop, multi-turn, bounded (`MAX_TURNS=12`). The stable KB/system block is
marked `cache_control: ephemeral` → 70–90% cost reduction on follow-up turns. Multi-turn (not single-pass)
because the user's mental model is iterative ("what's on H1? now zoom to M15. is there a sweep?"); the
REPL caps scope per turn. Each run writes a report (`report.py`), a per-tool-call JSONL trace
(`trace.py`), and a state snapshot whose diff is injected into the next run (`state.py`).

### KB injection (`kb/`)
Two-tier: an always-injected core (global rules, MOC, multi-TF, entry models, glossary — from
`config.toml`) plus query-triggered notes that `selector.py` keyword-matches against note frontmatter.
The KB is read-only from `../knowledge_base/`; the co-pilot never writes to it.

### Two frontends
- **REPL** (`cli.py`) — Anthropic SDK; commands: `analyze`, `switch`, `model`, `log`, `trades`, `edit`,
  `backtest`, `compare`, `stats`, `history`, `read`.
- **MCP server** (`mcp_server.py`) — same schemas over stdio, plus a `save_trade` tool; result cache
  persists for the process lifetime.

## Output format

Claude's final turn emits a structured markdown report (driven by the `prompts.py` template): Bias
(HTF/MTF/LTF) → **HTF POI** (the gate verdict) → Active Setup (LIVE/PENDING/INVALID) → Confirmed ✅ /
Pending ⏳ / Invalidates ❌ → Levels (entry/stop/TP1/TP2) → Orderflow → RR → **Management** → **Chart** →
What I Checked (each tool call + key finding). Reports persist to
`~/.trading-copilot/reports/{symbol}_{ts}.md`.
The anti-hallucination contract: **every price in the report must appear in at least one tool result** —
if check fails, treat it as a P0 bug.

### Analysis workflow rules (P1-2, in `_ROLE`)
The system prompt encodes the trader's methodology (`docs/TRADING_RULES_DRAFT.md`) as three load-bearing
rules:
- **HTF-POI hard gate.** No setup is LIVE without a valid higher-timeframe POI (OB/FVG/sponsored candle).
  A POI is valid only if it swept liquidity on formation, has no larger opposing pool behind it, sits in
  the right premium/discount zone, and is structure-synced. Gate failure → "No setup — no valid HTF POI".
- **Conflict hierarchy.** When detectors disagree, the higher tier wins: **market structure > liquidity
  sweep > OB/FVG (POI) > orderflow**. Orderflow (CD, volume profile) is context-only and may raise the
  entry threshold but never upgrade confidence or validate a setup on its own.
- **Position management.** Stop behind the POI extreme / SC wick; no break-even by default; 80% partial at
  the First Trouble Area + 20% at the main pool; sync→extend / desync→nearest pool; ≥1.5R.

A fourth rule governs the chart output: **CHART OUTPUT** requires a closing `generate_pine_script` call
carrying only the detectors that materially drove the verdict — the POI's source, whatever produced each
price in Levels, and the structure detector. Charting everything the analysis touched would put the
discarded evidence on the trader's chart next to the live setup. The registry writes the overlay to
`~/.trading-copilot/pine/` and returns `pine_file`, so the Pine text never enters the model's context.

The prompt reads volume-profile context (`current_price_location`, `nearest_hvn_*`, `hvn_nodes`) straight
from `detect_volume_profile` output — it does **not** call the `ob_in_hvn`/`poc_location`/`price_in_lvn`
composites, which are backtest-only (no `TOOL_SCHEMA`, so unregistered for the LLM). The cross-run state
diff (`state.py`) surfaces HTF-POI lifecycle changes (OB mitigation, breaker tested, SC mitigated)
alongside FVG fills, liquidity sweeps, POC shifts, and structure shifts.

## Verification

- **Per detector (automated):** `pytest tests/test_detectors_*.py` + `tests/test_probe_regression.py`,
  fixture-based with positive / negative / edge cases. See [CONVENTIONS.md](CONVENTIONS.md) test standards.
- **Visual:** per-detector debug files via `scripts/debug_detectors.py`, or the analysis overlay via
  `generate_pine_script`; overlay on TradingView and compare to high-rated community scripts. Both paths
  share `copilot/pine/`, so a zone drawn in one is the zone drawn in the other.
- **Agent loop:** `tests/test_agent_loop.py` mocks the Anthropic client with scripted `tool_use`
  responses; verifies the dispatcher calls the right detector with the right args. No real API in CI.
- **End-to-end (manual, per milestone):** run the REPL against live Binance during a killzone; confirm
  report structure, that every bullet maps to a tool call in the trace, and that no price is hallucinated.
