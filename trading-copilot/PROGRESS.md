# Trading Co-Pilot — Progress Report
_Last updated: 2026-04-26_

---

## What this project is

A Python system where Claude reads the user's SMC/ICT trading knowledge base as context, then calls algorithmic price detectors as tools over real OHLC data, and produces a structured market analysis. The trader reads the output and makes the final call — no order placement.

Two usage modes built and working:
- **CLI REPL** — `python -m copilot`, multi-turn chat, report saved to disk
- **MCP server** — detectors exposed as tools in Claude Desktop / Cowork

Full design rationale and architecture: see [PLAN.md](PLAN.md).

---

## Current state: Phases 1–6 + 9 cross-cutting improvements complete ✅

### What's built and tested

**Data layer** — Binance USD-M Futures (`fapi.binance.com`), parquet disk cache:
- [`copilot/data/binance.py`](copilot/data/binance.py) — futures by default (`market="futures"`), spot available as fallback. Up to 1500 bars/request. Also fetches `taker_buy_base_vol` for CD detector.
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

**Detector library — Orderflow (Phase 4)** — 2 primary + 4 composite:

| Detector | Concept | Key output fields |
|---|---|---|
| `detect_cumulative_delta` | Net buy pressure per bar (taker vol) | `session_delta`, `delta_trend`, `divergences`, `sweep_confirmation` |
| `detect_volume_profile` | Price acceptance/rejection zones from OHLCV | `poc`, `vah`, `val`, `hvn_nodes`, `lvn_nodes`, `current_price_location` |
| `check_ob_in_hvn` | OB price range overlaps ≥N% with any HVN node | `in_hvn`, `overlap_pct`, `hvn_price_mid` |
| `check_poc_location` | Current price relative to POC | `location` (above/below/at_poc), `in_discount`, `in_premium` |
| `check_price_in_lvn` | Is current close inside a thin-volume node? | `in_lvn`, `node` |
| `check_cd_absorption` | High-vol + small-range + close-near-high proxy | `absorption_detected`, `vol_ratio`, `range_atr_ratio` |

Volume Profile uses **triangular distribution** peaked at the bar's close (rather than uniform) to weight volume toward the close — more accurate for liquid instruments.

**Visualization tool:**

| Tool | Purpose | Output |
|---|---|---|
| `generate_pine_script` | Runs all detectors in parallel and emits a ready-to-paste Pine Script v5 overlay | `pine_script` (copy into TradingView), `zone_count`, `summary` |

Detectors run via `ThreadPoolExecutor(max_workers=9)` — parallel execution. Generated script includes `alertcondition()` calls at top level for BSL/SSL sweeps, FVG entries, OB touches, and VP POC/VAH/VAL crosses.

Zone color legend:
Teal/Red = FVG · Blue/Orange = OB · Lime/Maroon = IFVG · Aqua/Fuchsia = Breaker · Green/DarkRed = Mitigation Block · Navy/Purple = Rejection Block · Yellow dashed = BSL · Purple dashed = SSL

**KB layer**:
- [`copilot/kb/loader.py`](copilot/kb/loader.py) — reads Obsidian markdown, parses YAML frontmatter
- [`copilot/kb/selector.py`](copilot/kb/selector.py) — two-tier injection: always-core + keyword-triggered per query

**LLM layer** (CLI mode):
- [`copilot/llm/tools.py`](copilot/llm/tools.py) — auto-discovers `TOOL_SCHEMA` from detector modules; request-scoped result cache keyed `(tool, symbol, tf, bars)` — cleared between MCP calls, reused within one `analyze()` pass
- [`copilot/llm/agent.py`](copilot/llm/agent.py) — multi-turn tool-use loop, prompt caching on KB system block
- [`copilot/llm/prompts.py`](copilot/llm/prompts.py) — system prompt builder with KB + session context + previous-analysis diff injection
- [`copilot/llm/report.py`](copilot/llm/report.py) — saves reports to `~/.trading-copilot/reports/`
- [`copilot/llm/trace.py`](copilot/llm/trace.py) — appends one JSONL record per tool call to `~/.trading-copilot/traces/{SYMBOL}_{YYYYMMDD}.jsonl`; large list fields trimmed to first 3 items + count
- [`copilot/llm/state.py`](copilot/llm/state.py) — saves all detector results after each analysis to `~/.trading-copilot/reports/{SYMBOL}_{YYYYMMDD}.state.json`; loads previous state and injects a markdown diff (FVG fills, liquidity sweeps, POC shifts >0.5%, BOS changes) into the next analysis as `# Previous Analysis Context`

**MCP server** (Claude Desktop / Cowork mode):
- [`copilot/mcp_server.py`](copilot/mcp_server.py) — exposes **all 22 tools** (21 detectors + `generate_pine_script`) over stdio. Clears request-scoped cache before each dispatch.
- [`claude_desktop_config.json`](claude_desktop_config.json) — ready-to-merge Desktop registration config
- [`run_mcp.bat`](run_mcp.bat) — standalone launcher with correct PYTHONPATH

**CLI REPL**:
- [`copilot/cli.py`](copilot/cli.py) + [`copilot/session.py`](copilot/session.py)
- Commands: `analyze`, `switch <SYMBOL>`, `model <name>`, `verbose`, `history`, `read <N>`
- `log` — interactive prompt to record a new trade
- `trades [--setup X] [--result Y] [--symbol S] [--last N] [--account A] [--tag T]` — filtered table view
- `edit <id-prefix>` — update exit price, result, pnl_r, notes, tags
- `backtest --rule <name> --tf <tf> --bars <N> [--no-write] [--split <ratio>]` — bar-by-bar simulation; `--split 0.7` runs IS/OOS walk-forward and prints both metric sections
- `stats [--group setup|tool|session|dow|account|htf_bias] [--setup X] [--symbol S] [--last N]` — aggregated winrate / avg RR / profit factor / expectancy; `--group tool` shows tool-effectiveness ranking (Δwinrate vs baseline)

**Tests — 248/248 pass** (`python -m pytest tests/`):

| Test file | Count | Phase |
|---|---|---|
| `test_detectors_fvg.py` | 6 | 1 |
| `test_detectors_ms.py` | 6 | 1 |
| `test_detectors_bos.py` | 4 | 1 |
| `test_detectors_liquidity.py` | 4 | 1 |
| `test_detectors_ob.py` | 4 | 1 |
| `test_multi_tf.py` | 5 | 1 |
| `test_agent_loop.py` | 4 | 1 |
| `test_detectors_ifvg.py` | 6 | 2 |
| `test_detectors_breaker_block.py` | 5 | 2 |
| `test_detectors_rejection_block.py` | 6 | 2 |
| `test_detectors_compression.py` | 7 | 2 |
| `test_detectors_sessions.py` | 8 | 2 |
| `test_pine_script.py` | 11 | 2 |
| `test_journal.py` | 33 | 3 |
| `test_detectors_cumulative_delta.py` | 15 | 4 |
| `test_detectors_volume_profile.py` | 17 | 4 |
| `test_backtest_rules.py` | 23 | 5 |
| `test_backtest_simulate.py` | 19 | 5 |
| `test_backtest_engine.py` | 10 | 5 |
| `test_backtest_compare.py` | — | 6 |
| `test_backtest_rules_orderflow.py` | — | 6 |
| `test_detectors_orderflow_composite.py` | — | 6 |
| `test_stats_aggregator.py` | — | 6 |

**Journal module** (`copilot/journal/`):

| File | Purpose |
|---|---|
| [`copilot/journal/record.py`](copilot/journal/record.py) | `TradeRecord` dataclass + `compute_rr`, `session_from_ts`, `parse_ts` utilities |
| [`copilot/journal/db.py`](copilot/journal/db.py) | SQLite connection with WAL mode + schema (`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL`); deletes legacy `journal.jsonl` on first open |
| [`copilot/journal/writer.py`](copilot/journal/writer.py) | `append_record` (`INSERT OR IGNORE`), `update_record` (SQL `UPDATE`) |
| [`copilot/journal/reader.py`](copilot/journal/reader.py) | `load_all`, `filter_by` (SQL WHERE builder, 11 dimensions + tag post-filter), `get_by_id` (exact + prefix LIKE) |
| [`copilot/journal/__init__.py`](copilot/journal/__init__.py) | Re-exports all public API |

**Storage**: `~/.trading-copilot/journal/journal.db` — SQLite with WAL mode. List fields (`tp_prices`, `tools_confirmed`, `tags`, etc.) stored as JSON TEXT. Any legacy `journal.jsonl` is deleted on first open.

**Backtest module** (`copilot/backtest/`):

| File | Purpose |
|---|---|
| `rules.py` | `Condition` + `SetupRule` dataclasses, dotted-path field navigation, `evaluate_conditions()`, built-in rules (`fvg_ob_long`, `sweep_bos_long`, `ob_fvg_short`); `build_detector_registry(include_delta=True/False)` |
| `rules_orderflow.py` | Group A (VP-only), B (CD-only), C (VP+CD combined) orderflow-augmented rules; `sweep_cd_manipulation_long/short`, `poc_hvn_ob_long`, `sponsored_cd_ob_hvn_long`, `compression_vp_break_long` |
| `simulate.py` | `simulated_exit()` (SL wins on same-bar conflict), `resolve_entry/sl/tp()` |
| `engine.py` | `BacktestEngine.run()` — IDLE→SIGNAL→IN_TRADE state machine; `walkforward_split` param for IS/OOS split; `_run_loop()` private method; CD rules automatically get delta-enriched df |
| `report.py` | `trades_to_summary()`, `print_summary()`, `print_walkforward()`, `write_summary_to_journal()` |
| `compare.py` | `compare_live_vs_backtest()` — loads journal, splits live vs backtest records by `run_id`, prints side-by-side metrics |

**Stats module** (`copilot/stats/`):

| File | Purpose |
|---|---|
| `aggregator.py` | `compute_stats(records, group_by) → StatsResult`; metrics: winrate, avg RR, profit factor, expectancy; group by setup, tool, session, day_of_week, account_type, htf_bias, record_type |
| `cli.py` | REPL `stats` command; `--group tool` shows Δwinrate per tool vs baseline (tool-effectiveness ranking) |

**Detector bug fixes** (code review pass):
- `sponsored_candle`: return key `"sponsored"` → `"candles"`, item key `"type"` → `"ob_type"` — Group C backtest rules were silently broken
- `orderflow_composite.check_ob_in_hvn`: removed fallback to mitigated OB when no unmitigated OB found; returns `{in_hvn: false}` immediately instead
- `liquidity._count_touches`: removed dead `is_high` branching (both branches were identical)

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
3. Hammer icon in chat input → 22 tools visible

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
Append-only SQLite DB at `~/.trading-copilot/journal/journal.db` (WAL mode). One `TradeRecord` per trade or backtest entry. New REPL commands: `log`, `trades`, `edit <id>`.

### Phase 4 — Orderflow detectors ✅ DONE
`detect_cumulative_delta` (Binance taker vol), `detect_volume_profile` (triangular-weighted OHLCV approximation), plus 4 composite meta-detectors: `check_ob_in_hvn`, `check_poc_location`, `check_price_in_lvn`, `check_cd_absorption`.

### Phase 5 — Backtest engine ✅ DONE
Bar-by-bar historical simulation. Strict look-ahead prevention. Results written to journal as `record_type="backtest"`. Walk-forward split (`--split N`) for IS/OOS validation.

### Phase 6 — Statistics aggregation ✅ DONE
`copilot/stats/` — winrate, avg RR, profit factor, expectancy. Group by: setup, tool, session, day of week, account type, HTF bias, live vs backtest. Tool-effectiveness ranking: Δwinrate per confirmed tool vs baseline. Orderflow-augmented rules (Group A/B/C) in `rules_orderflow.py`. Live vs backtest comparison via `compare.py`.

### Cross-cutting improvements ✅ DONE (landed alongside Phase 6)
1. **Trace logs** — JSONL per tool call at `~/.trading-copilot/traces/{SYMBOL}_{YYYYMMDD}.jsonl`
2. **Pine Script alerts** — `alertcondition()` at top level for BSL/SSL, FVG, OB, VP levels
3. **Parallel detector execution** — `ThreadPoolExecutor(max_workers=9)` in `generate_pine_script`
4. **VP triangular distribution** — volume weighted toward close within each bar's range
5. **Request-scoped detector cache** — avoids recomputing same `(tool, symbol, tf, bars)` within one MCP call
6. **CD rules in backtest** — `build_detector_registry(include_delta=True)` makes Group B/C rules actually fire
7. **Walk-forward split** — `BacktestEngine.run(walkforward_split=0.7)` + `--split` CLI flag
8. **Analysis state persistence** — detector results saved per session; markdown diff injected into next analysis system prompt
9. **Journal: SQLite + WAL** — replaces JSONL; legacy file deleted on first open

### Phase 7 — Dashboard TUI (next)
`python -m copilot dashboard` → `rich` terminal UI: equity curve, rolling winrate, session heatmap, top setups by profit factor, tool leaderboard, worst conditions. Implemented with `rich.table` + `rich.panel`.

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
| Volume Profile from OHLCV (not tick data) | Triangular distribution over `[low, high]` peaked at close is a practical approximation for liquid crypto — real VP requires L2 tick data unavailable via public REST |
| SQLite WAL for journal | Concurrent reads during analysis don't block writes; WAL gives ~3× throughput vs default journal mode |
| Request-scoped detector cache | Within one MCP call Claude may invoke the same detector twice; cache avoids redundant Binance fetches |
| State persistence + diff injection | Analyst sees what changed since last run (filled FVGs, new sweeps, POC shifts) without re-reading old reports |
| Walk-forward split in backtest | Single IS/OOS validation run via `--split N`; avoids manual dataset splitting |
| `include_delta` flag in registry | CD detector opts into delta-enriched df — backtest engine enables it only for rules that need it |
