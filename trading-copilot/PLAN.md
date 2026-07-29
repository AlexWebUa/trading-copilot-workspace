# Trading Co-Pilot — Roadmap

The current approved list of steps and their state. **Nothing else lives here** — design is in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), engineering rules in [docs/CONVENTIONS.md](docs/CONVENTIONS.md),
what's built in [PROGRESS.md](PROGRESS.md), and why the project was re-audited in
[docs/AUDIT_HISTORY.md](docs/AUDIT_HISTORY.md).

> **Sequencing rule:** each later phase consumes data produced by the earlier ones. No feature work (P3+)
> until P0b–P1 land. "Profitable" is decided in the setup-R&D loop (step 6 of the agreed sequence), not by
> engineering alone — hold it as a hypothesis tested on out-of-sample data, not an outcome.
>
> **Corollary:** detector correctness and edge are independent. Finishing P0b–P2 will not create edge —
> it only makes the measurement trustworthy enough that the answer, either way, means something.

## Agreed next-step sequence

1. ~~**P1-3** — fix `agent.py` (multi-TF result keying + duplicate message).~~ ✅ done.
2. ~~**P2-1 / P2-2** — fix the degraded + quarantined detectors.~~ ✅ done. Every probe `xfail` flipped
   except the three quarantined tools.
3. ~~**P1-2** — revise the analysis workflow (HTF-POI gate, conflict hierarchy, position management).~~
   ✅ done.
4. **P0b (P0-8…P0-11)** — the three evidence-integrity bugs from the 2026-07-29 review, then re-run
   the re-baseline. **This is the current step and it blocks step 6**: the existing re-baseline numbers
   were produced by the buggy exit path, so they are not a valid starting point for rule R&D.
5. **P1-4** — probability assessment (HIGH/MED/LOW + reasons) on trustworthy detectors. Do this *after*
   there is journal data to calibrate the labels against, not before (see the note under P1-4).
6. **Setup R&D loop** — iterate setups/rules/management across multi-TF, multi-year data split by
   week/month; rank on **out-of-sample expectancy & profit factor** (not win rate). This is where edge is
   found or disproven. Blocked on P0b and on P2-3 + the bar-cap lift (see P2 table) — without confidence
   intervals and more than ~200 days of data, this step cannot distinguish edge from noise.
7. **Optional polish** — Pine design system — whenever; it gates nothing.

P3–P5 are feature work gated on P0b–P2 *correctness*, not on profitability.

## Completed

| Phase | Feature | Status |
|---|---|---|
| 1 | Walking skeleton (data, Tier A detectors, KB, LLM, REPL, MCP) | ✅ built |
| 2 | Tier B detectors + Pine Script generator | ✅ built |
| 3 | Trade Journal (SQLite WAL) | ✅ built |
| 4a/4b | Cumulative Delta + Volume Profile detectors | ✅ built |
| 5 | Backtest engine (walk-forward, HTF conditions, partial TP, fee model) | ✅ built |
| 6 | Statistics aggregation | ✅ built |
| 8a | Composite detectors (absorption_at_poi, cd_divergence_at_structure) | ✅ built (quarantined) |

> "Built" ≠ "validated." The June 2026 audit invalidated all Phase 5 backtest results and found Phases
> 4/8a detectors broken — see [docs/AUDIT_HISTORY.md](docs/AUDIT_HISTORY.md).

## P0 — Source-data & evidence integrity (DONE 2026-06-10)

| Item | Fix | Status |
|---|---|---|
| P0-1 | Drop forming bar in `normalize_binance` (`include_forming=False`) | ✅ DONE |
| P0-2 | Backtest look-ahead: LTF scan from signal-bar close; HTF slice by HTF bar close; cache key += kwargs; HTF respects start/end. Regression test `tests/test_lookahead_regression.py` | ✅ DONE |
| P0-3 | Add `smartmoneyconcepts`; rewrap swings / BOS-CHoCH / OB / FVG / liquidity (R1–R3). `smc_lib.py` adapter; OB keeps swing-break scan (smc.ob inherits R1) | ✅ DONE |
| P0-4 | Quarantine noise tools (`detect_compression`, `check_absorption_at_poi`, `check_cd_divergence_at_structure`); strip noisy CD fields | ✅ DONE |
| P0-5 | Rewrite CD divergence swing-to-swing; sweep anchoring to liquidity pools with side semantics (R4, R5) | ✅ DONE |
| P0-6 | Honest cost model: two-sided fees, slippage; fix `tools_confirmed`, `_resolve_limit_level` direction; route delta through cache. (Funding approximation deferred.) | ✅ DONE |
| P0-7 | Re-baseline all rules walk-forward — first trustworthy expectancy. Result: no rule shows a positive edge (narrow run; see AUDIT_HISTORY) | ✅ DONE |

## P0b — Evidence integrity (found 2026-07-29 review)

Same class as P0-1…P0-7: each one silently corrupts the evidence the rest of the roadmap consumes,
and none of them raises. All three are verified with reproductions, not suspected.

| Item | Fix | Effort | Status |
|---|---|---|---|
| **P0-8** | **Backtest never scans the entry bar.** Entry resolves at bar `signal+1` and `_IN_TRADE` exit scanning starts at `signal+2` (`backtest/engine.py`), so the entry bar's high/low are never tested — every trade gets one bar of stop immunity. Compounding it, `report.trades_to_summary` classifies only win/loss/be/expired, so a trade left `pending` at end-of-data is dropped from winrate/expectancy/PF entirely. Repro: flat 100-bar series, SL 98, entry-bar low 90 → `result=pending`, never exits. Bias is **optimistic**. Add to `tests/test_lookahead_regression.py` and decide explicitly what `pending` does to the stats | S | pending |
| **P0-9** | **`ToolRegistry` cache key omits detector kwargs.** `cache_key = (tool, symbol, tf, bars, start, end)` (`llm/tools.py`) — 15 of 16 exposed tools take params. Repro: `detect_order_block(swing_lookback=3)` then `(swing_lookback=25)` returns the *same object*. The LLM re-probing with a wider lookback silently reasons on the previous answer, and `_verify_report_numbers` cannot catch it because the numbers are genuine tool-result numbers. Same bug class as the P0-2 HTF cache-key fix | S | pending |
| **P0-10** | **MCP result cache has no TTL and is never cleared.** Documented as intentional in `mcp_server.call_tool`, but the key has no time component and `clear_cache()` is never called, while a Claude Desktop stdio server can live for hours. Asking for the same symbol/tf/bars later in the day returns the morning's candles — on the timeframe the system exists to read. `data/cache.py` has correct per-TF TTLs; this in-memory layer sits in front and defeats them | S | pending |
| **P0-11** | Re-run `scripts/rebaseline.py` and rewrite `REBASELINE_2026-06-10.md`. The current numbers came from the P0-8 exit path and are not a valid baseline | S | blocked by P0-8 |

## P1 — Test integrity & analysis workflow

| Item | Fix | Effort | Status |
|---|---|---|---|
| **P1-1** | Convert `probes/*.py` → `tests/test_probe_regression.py`; delete vacuous schema tests; fix probe `sys.path` | S | ✅ DONE 2026-06-19 — landed as 13 pass + 7 `xfail(strict)`; P2-1/P2-2 then flipped 4 of them, leaving 3 xfails (all quarantined tools) |
| **P1-3** | Fix `agent.py`: key tool results by `(name, symbol, tf)`; remove duplicate assistant append; add report-vs-trace anti-hallucination check (price-like report values absent from every tool result → loud stderr warning + trace record) | S | ✅ DONE 2026-06-19 — `_result_key` / `_verify_report_numbers`; `state.py` POC label reads the `@`-keyed tf; 5 tests in `test_agent_loop.py` |
| **P1-2** | Analysis workflow (`prompts.py` + `state.py`): HTF-POI hard gate, `## HTF POI` section, conflict hierarchy (MS > sweep > OB/FVG > orderflow), position management; remove noise-signal upgrade instructions | S | ✅ DONE 2026-06-22 — `_ROLE` HTF-POI hard gate + ranked conflict hierarchy + position-management policy; `_OUTPUT_FORMAT` adds `## HTF POI` + `## Management`, drops phantom `OB in HVN` row. Removed prompt calls to unregistered `check_ob_in_hvn`/`check_poc_location`/`check_price_in_lvn` (no `TOOL_SCHEMA`; `check_ob_in_hvn` audit-flagged broken) → read `detect_volume_profile` fields instead. `state.build_context_block` adds HTF-POI lifecycle diffs (OB mitigation, breaker tested, SC mitigated). 7 tests in `test_prompts_workflow.py` |
| **P1-4** | Trade probability assessment (HIGH/MED/LOW confidence with listed reasons) — only meaningful after detectors are correct. **Prerequisite:** persist each analysis's label to the journal so labels can later be scored against outcomes. A confidence label with no calibration data behind it is worse than none — it will be believed | S | pending |

## P2 — Detector fixes & honest reporting

| Item | Fix | Effort | Status |
|---|---|---|---|
| **P2-1** | Small fixes: `fib_zones` auto-direction (short OTE); `current_killzone` weekend gate; `multi_tf` single coherent path; `fractals` Williams 5-bar + swept/broken semantics; unify ATR on `true_range_atr`. `rejection_block` **quarantined** indefinitely (definition under manual revision). Also fixed the `debug_detectors.py` Pine offsets (forming-bar anchor, FVG C1 anchor, BOS swing→break). | S | ✅ DONE 2026-06-22 |
| **P2-2** | Rebuild breaker/mitigation/sponsored on the single library OB (R3); sponsored candle = sweep of a *pool* (R4) | M | ✅ DONE 2026-06-22 — shared `scan_order_blocks`; breaker pierce = close-through; sponsored = nearest-prior-pool sweep; mitigation = no prior sweep |
| **P2-3** | Binomial CI on winrates in `stats`; QuantStats tearsheet (`journal tearsheet`). **No longer optional** — the re-baseline has rules with 2–3 trades per split. Point estimates on those samples are noise, and step 6 ranks rules on them | S | pending |
| **P2-5** | Lift the 5000-bar cap in `engine._fetch_data` (~208 days of 1h). Step 6 calls for multi-year data split by week/month; the engine cannot fetch that today. Also decide the multiple-comparisons policy before R&D starts: fixed pre-registered rule set, rolling walk-forward folds rather than one 70/30 split, and "no edge" as an acceptable published result | M | pending |
| **P2-4** | Journal pattern analysis (`journal analyze`, LLM error detection) | M | pending |

## P3–P5 — Feature work (gated on P1–P2)

| Item | Notes | Status |
|---|---|---|
| P3 | Dashboard TUI (rich terminal) | blocked by P0–P1 |
| P3 | Multi-LLM provider abstraction | LOW — deferred |
| P4 | Screenshot / text trade analysis (multimodal) | blocked by P1-2 |
| P5 | More instruments (XAU → FX → indices); each = one `data/*.py` `DataSource`, detectors unchanged | blocked by stable crypto workflow |
| P5 | QoL: scheduled killzone reports, embeddings KB retrieval, report archive browser | deferred |

## Explicitly deferred
Order placement / broker APIs. Footprint imbalances & VWAP/TPO (L2/tick data unavailable on public REST).
Web/GUI frontend (REPL + TUI matches the discretionary workflow).
