# Trading Co-Pilot — Current State

_Last updated: 2026-09-15._ What exists and how trustworthy it is. Roadmap: [PLAN.md](PLAN.md). Design:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Why the trust caveats: [docs/AUDIT_HISTORY.md](docs/AUDIT_HISTORY.md).

## Headline

> **Start here next session: [HANDOFF.md](HANDOFF.md).**

**No setup has a demonstrated edge.** 30mOF ran on 2026-08-27 — 22 arms, a year
of 30m, honest costs — and not one arm's confidence interval cleared zero.
`bellissimo_1h3m_long` fell to +0.555R [-1.00, +2.09] when R-12 was fixed the
day before, and to **+0.201R [-1.31, +1.73]** once costs were charged
(`docs/SETUP_1H3M_BELLISSIMO.md` → прогон 5). Silver Bullet found none over 280
trades, and its one borderline arm, `sb_nyam_mkt_long`, fell from +0.633R
[+0.02, +1.26] to **+0.302R [-0.29, +0.92]** once costs were charged
(`docs/SETUP_ICT_SILVER_BULLET.md` → прогон 2). Do not quote any
pre-2026-08-27 backtest figure.

### Landed 2026-09-15

- **ORB, the trader's variant** — stop behind the last 3-candle fractal
  confirmed before the New York open (`sl_method="Fractal"`, floored by
  `min_stop_atr`), `tp_method="FixedR"`, and an order-flow bias on 1h/4h
  (`simulate(..., bias=...)`; `bias_series` releases a structure break only
  once its HTF candle has closed). All 12 cells negative on the first two
  years; the selected one repeated the loss on the held-out year.
  `docs/SETUP_ORB_ALGO.md`.
- **`sb_nyam_mkt_long` re-scored with costs** — the published result
  reproduces without costs (+0.633R vs +0.627R); costs take it to
  +0.302R [-0.29, +0.92]. The project's only formally positive arm is gone.
- `scripts/run_costs_recheck.py` takes `--start/--end`, so a re-score runs on
  the published window rather than "the last N bars".

### Two defects the 30mOF run exposed in the engine, not in the setups

- **Costs were never charged.** `SetupRule.fee_bps` and `slippage_bps` default
  to 0.0 and no rule file sets them — only `scripts/rebaseline.py` did. Every
  setup research run before 2026-08-27, Bellissimo and Silver Bullet included, scored
  free trades. Re-scoring confirmed it: costs are worth 0.354R per trade long
  and 0.590R short on Bellissimo, and 0.33R on `sb_nyam_mkt_long`.
- **A structural stop can land on the entry.** `sl_logic` pins the stop to a
  level, so an entry filling at a POI that sits on that level leaves near-zero
  risk — measured down to **$0.90** on BTC. Such trades clear `min_rr` more
  easily than real ones and then dominate the arm. Fixed by
  `SetupRule.min_stop_atr` (0.0 everywhere except 30mOF, which uses 0.5 per the
  trader's decision). Both are pinned in `tests/test_backtest_costs.py`.

Three setups are formalised — 1h3m Bellissimo, ICT Silver Bullet, 30mOF — each
against a chart example the trader verified bar by bar, and each with a golden
test. The engine, the data layer and the detectors they use are trustworthy; see
the caveats below for what is not.

### Landed 2026-09-14

- **30mOF run 2 complete** — 22 arms, three years of 30m, stop floor, costs.
  No edge; five arms confirmed negative (upper bound below zero). Touch beats
  full fill in all five readable POI pairs. `docs/SETUP_30MOF.md`.
- **ORB Algo (public TradingView script) ported** — `copilot/backtest/orb_algo.py`,
  calibrated to the trader's own dashboard exactly (35 / 12 / 20 / 37.5% /
  0.02% / 0.66%). Three years, two anchors: no edge once the take-profit fills
  at the close that triggered it and costs are charged. The published result
  rests mostly on booking that fill at the EMA. `docs/SETUP_ORB_ALGO.md`.
- **`fetch_ohlcv_batched` caps a request at 100 000 bars** — multi-year LTF
  windows have to be loaded in chunks (`scripts/run_orb.py`, `load_history`).
- **The canonical index is `datetime64[ms]`** — `DatetimeIndex.asi8` returns
  milliseconds, not nanoseconds. Guarded in `orb_algo` and `tests/test_orb_algo.py`.

### Landed 2026-08-27

- **30mOF run 1** — 22 arms, `docs/SETUP_30MOF.md` → «Прогон 1». No edge; the
  POI arms measured degenerate fills and are being re-run after the stop floor.
- **`min_stop_atr`** — floor on the structural stop, `simulate.resolve_sl`.
- **Cost model wired into the runner** — 4 bps fee + 2 bps slippage per side.
- **The sweep is linear now.** `detect_order_flow` at `lookback=8000` reproduces
  the unbounded walk exactly (500 slices, every field 100%,
  `research/runs/of_lookback.json`) and was confirmed end to end: the market
  arms re-ran field-for-field identical at 1.83x the speed. Three years of 30m
  went from ~2.7 h per arm to ~31 min.
- **Sharded runs** — `scripts/shard_*.sh`, `merge_shards.py`, `analyse_30mof.py`,
  `inspect_stops.py`, `measure_of_lookback.py`. 14 arms in 39 min instead of 2.8 h.
- **Windows are pinned** (`--start/--end`). Without it each arm scores a slightly
  different window, and parallel shards score seven different ones.

### Landed 2026-08-26

- **R-12** — `_htf_slice_asof` cuts the HTF frame at the entry bar's close.
  Two regression tests; measured impact recorded in `PLAN.md` and
  `docs/SETUP_1H3M_BELLISSIMO.md` (прогон 4).
- **LTF fetch cache** — `BatchedOHLCStore`, coverage-based. 20k 3m bars: 7.1 s
  cold, 0.0 s warm. The `-P 3` parallelism cap is obsolete.
- **BOS / cBOS renamed** to the trader's convention (cBOS = continuation,
  BOS = the break). Swapped once in `smc_lib.structure_events`, guarded by
  `test_continuation_is_named_cbos_not_bos`.
- **30mOF built** — `detect_order_flow` (single-pass structural walk + pool
  gate), `detect_bpr`, `detect_stb_bts`, `sl_logic="of_key"`, POI entry modes,
  28 rules across two stages, `scripts/run_30mof.py`.
- **Native Pine** — `copilot/pine/native/order_flow.pine` computes on the
  chart's own bars, so a generated file can no longer drift off its candles.
  `debug_detectors.py` now defaults to **futures**, not spot.

## Background (state as of 2026-07-29, kept for context)


All of Phases 1–6 + 8a are **built**. After the June 2026 audit, P0-1…P0-7 (source-data & evidence
integrity), P1-1/P1-2/P1-3 (test integrity + analysis workflow) and P2-1/P2-2 (detector repairs) are
**done**. The honest position today:

- **Trustworthy:** data layer (forming bar dropped), the smc-rewrapped core detectors (market_structure,
  bos, order_block, liquidity, fvg/ifvg), CD (rewritten), volume profile, the P2-repaired Tier B
  detectors (breaker/mitigation/sponsored on the shared swing-break OB, fractals, fib_zones, multi_tf,
  killzones), and the test suite (vacuous tests removed; probes encoded as regression tests).
- **Analysis workflow revised (P1-2 done):** the system prompt now enforces an HTF-POI hard gate, a ranked
  conflict hierarchy (MS > sweep > OB/FVG > orderflow), and the trader's position-management policy; the
  noise-signal "upgrade POI quality" path and the calls to unregistered `check_*` composites were removed.
  The `agent.py` multi-TF keying + anti-hallucination guard is fixed (P1-3).
- **P0b is now DONE** (P0-8/P0-9/P0-10 landed Aug 2026), and so is R-12, the fourth bug of the same
  class found on 2026-08-26. `REBASELINE_2026-06-10.md` remains superseded — P0-11 was never re-run and
  is low value, since the research protocol excludes the 12 synthetic rules it measures.
- **Still pending:** P1-4 (HIGH/MED/LOW probability assessment), the intrabar-sweep change for
  Bellissimo, and P2-4 (journal pattern analysis).
- **No demonstrated edge yet.** The one re-baseline run found none — but it was narrow (1 symbol/TF, 2000
  bars, 2–3 trades per split on several rules) *and* produced by the buggy exit path. Finding edge is the
  setup-R&D loop, still ahead, and it is blocked on P0b + P2-3 + P2-5.

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
| `detect_order_flow` | ✅ new (2026-08-26) | single-pass structural walk; golden test on the trader's own 25-27 Jul markup |
| `detect_bpr`, `detect_stb_bts` | ✅ new (2026-08-26) | POI zones 30mOF enters from; BPR is rare by construction (~2% of slices) |
| `detect_rejection_block` | ⛔ quarantined | definition under manual revision by the trader (P2-1) |
| `detect_compression`, `check_cd_absorption`, `check_absorption_at_poi`, `check_cd_divergence_at_structure` | ⛔ quarantined | hidden from the LLM until rewritten (P0-4) |

## What's built (modules)

- **`data/`** — Binance USD-M futures (`fapi.binance.com`, spot fallback), parquet TTL cache, canonical
  OHLCV schema, `DataSource` protocol. Forming candle dropped. Delta from kline `taker_buy_base_vol`.
- **`detectors/`** — 23 tools + `generate_pine_script`, which charts only the detectors the analysis
  deemed significant (the LLM passes `detectors=[...]`; parallel `ThreadPoolExecutor`, TradingView v6
  overlay with per-layer toggles and `alertcondition()`s). `smc_lib.py` wraps `smartmoneyconcepts`.
  Added Aug 2026 for 30mOF: `order_flow.py` (structural walk + pool gate), `bpr.py`, `stb_bts.py`.
- **`pine/`** — the Pine generator itself, shared with `scripts/debug_detectors.py`: 19 per-detector
  emitters (moved out of the script, byte-identical), the runner table, `build_overlay`, and the
  artifact store. 12 layers are chartable — quarantined detectors, the delta layer and the two
  info-table emitters are excluded (see `OVERLAY_LAYERS`).
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
  orderflow (Group A/B/C) rules. **All pre-fix backtest numbers were invalid; the re-baseline found no
  edge — and is itself superseded by P0-8 (entry bar never scanned for SL/TP). Do not quote any backtest
  number until P0-11 re-runs it.** Hard-capped at 5000 bars per run (P2-5).
- **`stats/`** — winrate / avg RR / profit factor / expectancy; group by setup/tool/session/dow/account/
  htf_bias/record_type; tool-effectiveness Δwinrate ranking.
- **`mcp_server.py`** — exposes the (non-quarantined) registry over stdio + a `save_trade` tool.

## Tests

`354 collected: 351 passed + 3 xfailed, 0 failed` in ~4s (`.venv/bin/python -m pytest`). All fixtures are
programmatic; no network, no parquet files.

- `tests/test_probe_regression.py` — the 20 June probes as behavioral tests. Landed as 13 pass + 7
  `xfail(strict)`; P2-1/P2-2 flipped 4 of those, so **3 xfails remain** — `detect_compression`,
  `check_cd_absorption`, `detect_rejection_block`, all quarantined and all still broken by design. Flip
  to XPASS (failing the suite) the moment a fix lands, forcing the marker's removal.
- `tests/test_lookahead_regression.py` — guards the P0-2 backtest look-ahead fixes. **Does not yet cover
  the P0-8 entry-bar gap** — add it there when P0-8 lands.
- `tests/test_detectors_smc_rewrap.py` — guards the P0-3 rewraps.
- `tests/test_agent_loop.py` — guards P1-3 (multi-TF result keying, single assistant turn,
  `_verify_report_numbers`).
- `tests/test_prompts_workflow.py` — guards P1-2 (HTF-POI gate + hierarchy + management present in the
  prompt; phantom/quarantined tool names absent; `state.py` HTF-POI lifecycle diffs).
- Vacuous schema tests removed (`test_detectors_liquidity.py` deleted; behavior now covered by probes).

**Coverage gap:** 351 tests cover detectors; the LLM analysis output — the actual product — has no
evaluation beyond structural prompt assertions. Nothing scores an analysis against what price did next.

## Two usage modes
- **CLI REPL** — `.venv/bin/python -m copilot`; `analyze`, `switch`, `model`, `log`, `trades`, `edit`,
  `backtest`, `compare`, `stats`, `history`, `read`.
- **MCP server** — `./run_mcp.sh`; detectors as tools in Claude Desktop / Cowork (merge
  `claude_desktop_config.json`).
