# Trading Co-Pilot — Progress Report
_Last updated: 2026-04-25_

---

## What this project is

A Python system where Claude reads the user's SMC/ICT trading knowledge base as context, then calls algorithmic price detectors as tools over real OHLC data, and produces a structured market analysis. The trader reads the output and makes the final call — no order placement.

Two usage modes built and working:
- **CLI REPL** — `python -m copilot`, multi-turn chat, report saved to disk
- **MCP server** — detectors exposed as tools in Claude Desktop / Cowork

Full design rationale and architecture: see [PLAN.md](PLAN.md).

---

## Current state: Phase 1 + MCP + Phase 2 + Pine Script + Phase 3 (Trade Journal) + Phase 4 (Orderflow) complete ✅

### What's built and tested

**Data layer** — Binance USD-M Futures (`fapi.binance.com`), parquet disk cache:
- [`copilot/data/binance.py`](copilot/data/binance.py) — futures by default (`market="futures"`), spot available as fallback. Up to 1500 bars/request.
- [`copilot/data/cache.py`](copilot/data/cache.py) — TTL-based parquet cache, keyed `binance_futures_*`
- [`copilot/data/normalize.py`](copilot/data/normalize.py) — canonical OHLCV schema shared by all detectors
- [`copilot/data/base.py`](copilot/data/base.py) — `DataSource` protocol for future instrument sources

**Detector library — Tier A (Phase 1)** — 8 pure functions, each with `TOOL_SCHEMA` co-located:

| Detector | Concept | Key output fields |
|---|---|---|
| `detect_market_structure` | HH/HL vs LH/LL swing state | `state`, `last_swing_high/low`, `strength` |
| `detect_bos` | BOS / MSS / cBOS by candle close | `type`, `broken_level`, `displacement_atr_multiple` |
| `detect_fvg` | 3-candle imbalance zones | `upper/lower`, `fill_state` (untouched/IOFED/CE_tagged) |
| `detect_order_block` | Last opposing candle before impulse | `has_fvg_after`, `is_mitigated`, `distance_atr` |
| `detect_liquidity` | EQH/EQL pools + wick sweeps | `buyside/sellside_liquidity`, `recent_sweeps` |
| `detect_fib_zones` | Premium/Discount/OTE bands | `current_price_location`, `in_ote`, `key_levels` |
| `detect_fractals` | 3-bar local extrema | `is_swept`, `age_bars` |
| `check_multi_tf_alignment` | HTF vs LTF reconciliation | `ltf_role` (pullback/continuation), `sync_quality` |

**Detector library — Tier B (Phase 2)** — 7 additional pure functions:

| Detector | Concept | Key output fields |
|---|---|---|
| `detect_ifvg` | Inverted FVG — polarity-flipped zone after full pierce | `type` (inverted), `is_tested`, `width_atr_fraction` |
| `detect_breaker_block` | OB fully pierced → inverted polarity zone | `type` (inverted), `is_tested`, `original_ob_type` |
| `detect_mitigation_block` | OB formed without prior liquidity sweep | `is_mitigated`, `note` (no prior sweep) |
| `detect_rejection_block` | 2-candle body-engulf reversal zone | `type`, `c1_body_size_atr`, `is_mitigated`, `is_tested` |
| `detect_sponsored_candle` | OB preceded by confirmed sweep — highest-quality OB | `sweep_ts`, `sweep_side`, `is_mitigated` |
| `detect_compression` | LRLR narrowing range before expansion | `bars`, `squeeze_ratio`, `is_active`, `tightest_range_atr` |
| `current_killzone` | Current Kyiv time + active killzone + OTT state | `active_killzone`, `in_ott_window`, `next_killzone` |

**Detector library — Orderflow (Phase 4)** — 2 pure functions:

| Detector | Concept | Key output fields |
|---|---|---|
| `detect_cumulative_delta` | Net buy pressure per bar (taker vol) | `session_delta`, `delta_trend`, `divergences`, `sweep_confirmation` |
| `detect_volume_profile` | Price acceptance/rejection zones from OHLCV | `poc`, `vah`, `val`, `hvn_nodes`, `lvn_nodes`, `current_price_location` |

**Visualization tool:**

| Tool | Purpose | Output |
|---|---|---|
| `generate_pine_script` | Runs all detectors and emits a ready-to-paste Pine Script v5 overlay | `pine_script` (copy into TradingView), `zone_count`, `summary` |

Zone color legend in the generated script:  
Teal/Red = FVG · Blue/Orange = OB · Lime/Maroon = IFVG · Aqua/Fuchsia = Breaker · Green/DarkRed = Mitigation Block · Navy/Purple = Rejection Block · Yellow dashed = BSL · Purple dashed = SSL

**KB layer**:
- [`copilot/kb/loader.py`](copilot/kb/loader.py) — reads Obsidian markdown, parses YAML frontmatter
- [`copilot/kb/selector.py`](copilot/kb/selector.py) — two-tier injection: always-core + keyword-triggered per query

**LLM layer** (CLI mode):
- [`copilot/llm/tools.py`](copilot/llm/tools.py) — auto-discovers `TOOL_SCHEMA` from detector modules, no manual registry
- [`copilot/llm/agent.py`](copilot/llm/agent.py) — multi-turn tool-use loop, prompt caching on KB system block
- [`copilot/llm/prompts.py`](copilot/llm/prompts.py) — system prompt builder with KB + session context injection
- [`copilot/llm/report.py`](copilot/llm/report.py) — saves reports to `~/.trading-copilot/reports/`

**MCP server** (Claude Desktop / Cowork mode):
- [`copilot/mcp_server.py`](copilot/mcp_server.py) — exposes **all 18 tools** (17 detectors + `generate_pine_script`) over stdio. Auto-discovers from the same `ToolRegistry` used by the CLI — no schema duplication.
- [`claude_desktop_config.json`](claude_desktop_config.json) — ready-to-merge Desktop registration config
- [`run_mcp.bat`](run_mcp.bat) — standalone launcher with correct PYTHONPATH

**CLI REPL**:
- [`copilot/cli.py`](copilot/cli.py) + [`copilot/session.py`](copilot/session.py)
- Commands: `analyze`, `switch <SYMBOL>`, `model <name>`, `verbose`, `history`, `read <N>`
- Unrecognised input → treated as a follow-up query (chat mode)

**Tests — 141/141 pass** (`python -m pytest tests/`):
- `test_detectors_fvg.py` — 6 tests
- `test_detectors_ms.py` — 6 tests
- `test_detectors_bos.py` — 4 tests (including MSS detection)
- `test_detectors_liquidity.py` — 4 tests
- `test_detectors_ob.py` — 4 tests
- `test_multi_tf.py` — 5 tests
- `test_agent_loop.py` — 4 tests (mocked Anthropic; no real API calls in CI)
- `test_detectors_ifvg.py` — 6 tests *(Phase 2)*
- `test_detectors_breaker_block.py` — 5 tests *(Phase 2)*
- `test_detectors_rejection_block.py` — 6 tests *(Phase 2)*
- `test_detectors_compression.py` — 7 tests *(Phase 2)*
- `test_detectors_sessions.py` — 8 tests *(Phase 2)*
- `test_pine_script.py` — 11 tests *(Pine Script)*
- `test_journal.py` — 33 tests *(Phase 3: Trade Journal)*
- `test_detectors_cumulative_delta.py` — 15 tests *(Phase 4: Orderflow)*
- `test_detectors_volume_profile.py` — 17 tests *(Phase 4: Orderflow)*

**Journal module** (`copilot/journal/`):

| File | Purpose |
|---|---|
| [`copilot/journal/record.py`](copilot/journal/record.py) | `TradeRecord` dataclass + `compute_rr`, `session_from_ts`, `parse_ts` utilities |
| [`copilot/journal/writer.py`](copilot/journal/writer.py) | `append_record` (JSONL append), `update_record` (in-place rewrite) |
| [`copilot/journal/reader.py`](copilot/journal/reader.py) | `load_all`, `filter_by` (11 dimensions), `get_by_id` (prefix match) |
| [`copilot/journal/__init__.py`](copilot/journal/__init__.py) | Re-exports all public API |

**New REPL commands**:
- `log` — interactive prompt to record a new trade; auto-detects session from ts_entry (Kyiv TZ), auto-computes R:R from entry/SL/TP1
- `trades [--setup X] [--result Y] [--symbol S] [--last N] [--account A] [--tag T]` — filtered table view
- `edit <id-prefix>` — update exit price, result, pnl_r, notes, tags on a pending record

**Storage**: `~/.trading-copilot/journal/journal.jsonl` — append-only, one JSON object per line.

**Record schema tags** used for aggregation (Phase 6): `symbol`, `account_type`, `setup_name`, `tools_confirmed`, `direction`, `result`, `session`, `killzone`, `day_of_week`, `htf_bias`, `record_type` (trade vs backtest).

---

## How to run

### CLI REPL
```bash
cd D:\Projects\vibecoding\trading-copilot-workspace\trading-copilot

# First time only
cp .env.example .env
# Edit .env → add ANTHROPIC_API_KEY=sk-ant-...
pip install -e ".[dev]"

python -m copilot
python -m copilot --symbol ETHUSDT --verbose
```

### Claude Desktop (MCP)
1. Merge [`claude_desktop_config.json`](claude_desktop_config.json) into `%APPDATA%\Claude\claude_desktop_config.json`
2. Fully quit and relaunch Claude Desktop
3. Hammer icon in chat input → 16 tools visible

### Cowork project setup
1. Create a Cowork project
2. Attach KB files as project context:
   - `knowledge_base/00_Index/_Global_Rules.md`
   - `knowledge_base/01_Concepts/Multi_TF_Analysis.md`
   - `knowledge_base/08_Entry_Models/Entry_Models.md`
   - `knowledge_base/99_Glossary/Glossary.md`
   - Any active setup notes (e.g. `09_Setups/1h3m_by_Bellissimo.md`)
3. Paste system instruction from `COWORK_INSTRUCTION` in `mcp_server.py`
4. Connect `trading-copilot` MCP server in project settings

---

## Roadmap

### Phase 3 — Trade Journal ✅ DONE

Append-only `journal.jsonl` at `~/.trading-copilot/journal/`. One `TradeRecord` per trade or backtest entry. Schema covers: symbol, account_type (demo/phase1/phase2/live), setup_name, tools_confirmed, direction, entry/exit/SL/TP prices, result, pnl_r, session, killzone, day_of_week, htf_bias, tags.

New module: `copilot/journal/` (record, writer, reader). New REPL commands: `log`, `trades`, `edit <id>`.

This is the **foundation** for Phases 5–7 — no stats or backtest without clean journal data.

### Phase 4 — Orderflow detectors ✅ DONE

| Detector | Status | Data source |
|---|---|---|
| `detect_cumulative_delta` | ✅ | Binance klines `taker_buy_base_vol` — exact candle-level delta, single API call |
| `detect_volume_profile` | ✅ | OHLCV approximation: distribute bar volume uniformly over `[low, high]` buckets |
| `detect_footprint_imbalances` | DEFERRED | Requires intra-candle L2 data, unavailable via public REST |

**`detect_cumulative_delta`** — returns `session_delta`, `delta_trend` (positive/negative/neutral), `divergences` (bearish/bullish price–CD divergence), `sweep_confirmation` (wick sweep + delta contradiction = manipulation signal). Uses `fetch_ohlcv_with_delta()` dispatched via `_DELTA_TOOLS` in `ToolRegistry`.

**`detect_volume_profile`** — returns `poc`, `vah`, `val`, `hvn_nodes`, `lvn_nodes` (each with `price_mid/low/high`, `volume_pct`), `current_price_location`, `nearest_hvn/lvn_above/below` with `distance_atr`. Supports `session_bars` for intraday vs composite profiles.

### Phase 5 — Backtest engine (MEDIUM, after Phase 3+4 schemas are frozen)

`copilot/backtest/` — runs detectors over historical OHLC bar-by-bar (no look-ahead). Each triggered entry written to journal as `record_type="backtest"`. Enables live vs backtest comparison on the same metrics.

### Phase 6 — Statistics aggregation (MEDIUM, after ≥30 journal records)

`copilot/stats/` — winrate, avg RR, profit factor, expectancy. Group by: setup, tool, session, day of week, account type, live vs backtest. **Tool-effectiveness ranking**: which tools actually shift winrate vs which are noise.

### Phase 7 — Dashboard TUI (LOW-MEDIUM, after Phase 6)

`python -m copilot dashboard` — rich terminal UI: equity curve, rolling winrate, session heatmap, top setups, tool leaderboard, worst conditions.

### Phase 8 — Quality-of-life (ongoing, LOW)
- Scheduled reports at killzone times (09:00 / 15:00 / 17:00 Kyiv)
- Embeddings-based KB retrieval if keyword matching proves brittle
- Report archive browser in REPL (`history`, `read`)

### Phase 9 — More instruments (after crypto workflow is solid)

Deferred until Phases 3–7 are stable. Scope: **XAU/USD → EUR/USD → GER40 + EU50 → NAS100 + SP500**.
Each = one new `copilot/data/*.py` implementing `DataSource`. Detectors unchanged.

---

## Key design decisions

| Decision | Rationale |
|---|---|
| Futures data by default | Discretionary traders trade perps, not spot; funding rates already priced in |
| Detectors are pure functions | Unit-testable without live API; LLM gets compact JSON, not raw arrays |
| `TOOL_SCHEMA` co-located with detector | Adding a detector = one file, zero registry changes (works for both CLI and MCP) |
| MCP server reuses `ToolRegistry` | Single source of truth — schemas registered once, served to Anthropic API and Desktop identically |
| Backward scan in BOS detector | Finds the *most recent* structural break, not the first mid-trend cBOS |
| Prompt caching on KB system block | KB is large and stable per session → 70–90% token cost reduction on follow-ups |
| KB read-only from `knowledge_base/` | KB evolves independently; co-pilot never writes to it |
| `fill_state` enum over raw fill % | LLM reasons better over "CE_tagged" than "51.3%" |
| `closed_back: true` on sweeps | Distinguishes confirmed wick-sweeps from mere touches — critical for 1h3m setup validation |
| IFVG + Breaker: polarity-inversion pattern | Both are "zone that flipped" — shared logic, different formation path |
| Mitigation Block: no-sweep qualifier | Distinguishes from Sponsored Candle — helps LLM explain WHY a zone is a draw |
| `current_killzone` as MCP tool | Claude Desktop has no system clock access; tool gives it live Kyiv session context |
| `detect_compression` returns `is_active` | LLM can immediately answer "is price coiling right now?" without post-processing |
| `generate_pine_script` orchestrates all detectors | Single tool call gives the trader a paste-ready TradingView chart — no manual zone-drawing |
| `_PASS_META_TOOLS` in registry | Pine Script needs symbol/tf for header labels — clean opt-in, doesn't touch other tool dispatch |
| Binance klines for CD (not aggTrades) | `taker_buy_base_vol` in klines gives exact candle-level taker buy volume in a single request — aggTrades would need 200+ paginated calls for 24h BTC data |
| `_DELTA_TOOLS` dispatch path in registry | Detectors needing `buy_vol/sell_vol/delta` opt into a separate fetch path — clean separation from plain OHLCV tools |
| Volume Profile from OHLCV (not tick data) | Distributing bar volume uniformly over `[low, high]` is a practical approximation for liquid crypto — real VP requires L2 tick data unavailable via public REST |
