# Trading Co-Pilot — Current State

_Last updated: 2026-06-22._ What exists and how trustworthy it is. Roadmap: [PLAN.md](PLAN.md). Design:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Why the trust caveats: [docs/AUDIT_HISTORY.md](docs/AUDIT_HISTORY.md).

## Headline

All of Phases 1–6 + 8a are **built**. After the June 2026 audit, P0-1…P0-7 (source-data & evidence
integrity) and P1-1 (test integrity) are **done**. The honest position today:

- **Trustworthy:** data layer (forming bar dropped), the smc-rewrapped core detectors (market_structure,
  bos, order_block, liquidity, fvg/ifvg), CD (rewritten), volume profile, the backtest engine (look-ahead
  fixed, two-sided costs), and the test suite (vacuous tests removed; probes encoded as regression tests).
- **Analysis workflow revised (P1-2 done):** the system prompt now enforces an HTF-POI hard gate, a ranked
  conflict hierarchy (MS > sweep > OB/FVG > orderflow), and the trader's position-management policy; the
  noise-signal "upgrade POI quality" path and the calls to unregistered `check_*` composites were removed.
  The `agent.py` multi-TF keying + anti-hallucination guard is fixed (P1-3).
- **Still pending:** P1-4 (HIGH/MED/LOW probability assessment with listed reasons).
- **No demonstrated edge yet.** The one re-baseline run found none, but it was narrow (1 symbol/TF, 2000
  bars). Finding edge is the setup-R&D loop, still ahead.

## Detector inventory & verdicts

Verdicts from [DETECTOR_REVIEW_2026-06-10.md](DETECTOR_REVIEW_2026-06-10.md); exposure enforced by
`_QUARANTINED_TOOLS` in `copilot/llm/tools.py`.

| Detector | State | Notes |
|---|---|---|
| `detect_fvg`, `detect_ifvg` | ✅ correct | exact bounds; `join_consecutive` merges impulse gaps |
| `detect_volume_profile`, `check_poc_location`, `check_price_in_lvn` | ✅ correct | triangular dist. peaked at close |
| `detect_market_structure`, `detect_bos` | ✅ rewrapped (P0-3) | wrap `smc.bos_choch`; no right-edge synthetic swing |
| `detect_order_block` | ✅ rewrapped (P0-3) | swing-break scan over RAW confirmed swings (smc.ob inherits R1) |
| `detect_liquidity` | ✅ rewrapped (P0-3) | side-typed close-back sweeps |
| `detect_cumulative_delta` | ✅ rewritten (P0-5) | swing-to-swing divergence; pool-anchored sweep |
| `detect_fractals`, `check_multi_tf_alignment`, `current_killzone`, `detect_fib_zones` | ✅ fixed (P2-1) | Williams 5-bar fractals + swept/broken; weekend gate; single MTF path; auto-direction OTE |
| `detect_mitigation_block`, `detect_sponsored_candle`, `detect_breaker_block` | ✅ fixed (P2-2) | all on the shared swing-break OB (`scan_order_blocks`, R3); sponsored/mitigation use nearest-prior-pool sweeps (R4); breaker pierce = close-through |
| `detect_rejection_block` | ⛔ quarantined | definition under manual revision by the trader (P2-1) |
| `detect_compression`, `check_cd_absorption`, `check_absorption_at_poi`, `check_cd_divergence_at_structure` | ⛔ quarantined | hidden from the LLM until rewritten (P0-4) |

## What's built (modules)

- **`data/`** — Binance USD-M futures (`fapi.binance.com`, spot fallback), parquet TTL cache, canonical
  OHLCV schema, `DataSource` protocol. Forming candle dropped. Delta from kline `taker_buy_base_vol`.
- **`detectors/`** — 23 tools + `generate_pine_script` (parallel `ThreadPoolExecutor`, TradingView v5
  overlay with `alertcondition()`s). `smc_lib.py` wraps `smartmoneyconcepts`.
- **`llm/`** — `ToolRegistry` (auto-discovery, quarantine, request-scoped cache), multi-turn agent with
  ephemeral KB prompt caching, report/trace/state persistence. Tool results keyed by `(name, symbol, tf)`
  (no multi-TF overwrite); single assistant turn per round; `_verify_report_numbers` flags report prices
  absent from every tool result (P1-3 done). `prompts.py` encodes the P1-2 workflow (HTF-POI hard gate,
  conflict hierarchy, position management, `## HTF POI` + `## Management` report sections; reads volume-
  profile fields directly instead of phantom `check_*` tools); `state.py` diff adds HTF-POI lifecycle
  changes (OB mitigation, breaker tested, SC mitigated).
- **`kb/`** — Obsidian loader + two-tier selector (always-core + keyword-triggered).
- **`journal/`** — SQLite (WAL) at `~/.trading-copilot/journal/journal.db`; `TradeRecord` for live trades
  and backtest entries; auto-migrations.
- **`backtest/`** — bar-by-bar state machine (IDLE→SIGNAL→LTF_SCAN→IN_TRADE→IN_TRADE_P2), HTF conditions
  with per-bar cache, partial TP, time exit, two-sided fees + slippage, walk-forward split. Built-in +
  orderflow (Group A/B/C) rules. **All pre-fix backtest numbers were invalid; re-baseline found no edge.**
- **`stats/`** — winrate / avg RR / profit factor / expectancy; group by setup/tool/session/dow/account/
  htf_bias/record_type; tool-effectiveness Δwinrate ranking.
- **`mcp_server.py`** — exposes the (non-quarantined) registry over stdio + a `save_trade` tool.

## Tests

`354 collected: 351 passed + 3 xfailed, 0 failed` (`.venv/bin/python -m pytest`).

- `tests/test_probe_regression.py` — the 20 June probes as behavioral tests (13 pass + 7 `xfail(strict)`
  documenting unfixed P2-tier bugs; flip to XPASS when fixed).
- `tests/test_lookahead_regression.py` — guards the P0-2 backtest look-ahead fixes.
- `tests/test_detectors_smc_rewrap.py` — guards the P0-3 rewraps.
- `tests/test_agent_loop.py` — guards P1-3 (multi-TF result keying, single assistant turn,
  `_verify_report_numbers`).
- `tests/test_prompts_workflow.py` — guards P1-2 (HTF-POI gate + hierarchy + management present in the
  prompt; phantom/quarantined tool names absent; `state.py` HTF-POI lifecycle diffs).
- 2 breaker-block tests are `xfail(strict)` on the known P2-2 bug.
- Vacuous schema tests removed (`test_detectors_liquidity.py` deleted; behavior now covered by probes).

## Two usage modes
- **CLI REPL** — `.venv/bin/python -m copilot`; `analyze`, `switch`, `model`, `log`, `trades`, `edit`,
  `backtest`, `compare`, `stats`, `history`, `read`.
- **MCP server** — `./run_mcp.sh`; detectors as tools in Claude Desktop / Cowork (merge
  `claude_desktop_config.json`).
