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
| **P0-8** | **Backtest never scans the entry bar.** Entry resolves and `_IN_TRADE` scanning starts on the NEXT bar, so every trade got one bar of stop immunity; trades left `pending` at end-of-data were dropped from winrate/expectancy/PF entirely | S | ✅ DONE 2026-08-22 — fix is **per entry mode** (`_ENTRY_BAR_EXPOSED`): `next_open`/`fvg_ce`/`ob_midpoint` now settle the entry bar, while `signal_close` still must not (its range precedes the fill — scanning it would invent stop-outs and flip the bias pessimistic). The LTF entry path was already correct. `pending` stays out of every statistic but is counted and printed as «N сделок не завершилось». Measured bias on `fvg_ob_long`, BTCUSDT 1h, 8000 bars: expectancy +0.131R → +0.082R, PF 1.211 → 1.128 |
| **P0-9** | **`ToolRegistry` cache key omits detector kwargs.** `cache_key = (tool, symbol, tf, bars, start, end)` (`llm/tools.py`) — 15 of 16 exposed tools take params. Repro: `detect_order_block(swing_lookback=3)` then `(swing_lookback=25)` returns the *same object*. The LLM re-probing with a wider lookback silently reasons on the previous answer, and `_verify_report_numbers` cannot catch it because the numbers are genuine tool-result numbers. Same bug class as the P0-2 HTF cache-key fix | S | ✅ DONE 2026-08-22 — key now carries a sorted JSON dump of the kwargs; regression tests in `tests/test_lookahead_regression.py` cover both a differing re-probe and a still-caching identical call |
| **P0-10** | **MCP result cache has no TTL and is never cleared.** Documented as intentional in `mcp_server.call_tool`, but the key has no time component and `clear_cache()` is never called, while a Claude Desktop stdio server can live for hours. Asking for the same symbol/tf/bars later in the day returns the morning's candles — on the timeframe the system exists to read. `data/cache.py` has correct per-TF TTLs; this in-memory layer sits in front and defeats them | S | ✅ DONE 2026-08-23 — entries now carry a `time.monotonic()` stamp and expire on the per-TF TTL **imported from `data/cache.py`**, not re-declared, so the two layers cannot drift. Tools with no timeframe get the tightest TTL in the table (60 s) rather than living forever |
| **P0-11** | Re-run `scripts/rebaseline.py` and rewrite `REBASELINE_2026-06-10.md`. The current numbers came from the P0-8 exit path and are not a valid baseline | S | pending — unblocked (P0-8 done); re-run once the 1h3m rules land so the baseline covers what is actually being researched |

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
| **P2-3** | Binomial CI on winrates in `stats`; QuantStats tearsheet (`journal tearsheet`). **No longer optional** — the re-baseline has rules with 2–3 trades per split. Point estimates on those samples are noise, and step 6 ranks rules on them | S | ✅ DONE 2026-08-23 — Wilson interval for winrate (normal approx. is unusable at n<30) + fixed-seed percentile bootstrap for expectancy, both on `BacktestSummary` and printed with an explicit verdict (`edge` / `negative` / `indistinguishable from zero`). Immediately demoted the Bellissimo short arm from «+0.361R edge» to «+0.065R, CI [−0.76, +1.08]». QuantStats tearsheet still pending |
| **P2-5** | Lift the 5000-bar cap in `engine._fetch_data`. Step 6 calls for multi-year data split by week/month; the engine could not fetch that | M | ✅ DONE 2026-08-22 — cap removed, and the **real** ceiling turned out to be 1500: `get_ohlc(bars=5000)` silently returned 1499 because Binance caps `limit` per request and the source never paginated. `BinanceSource._paginate_back` walks back in 1500-bar pages; disk cache versioned (`_CACHE_VERSION = 2`) so pre-fix entries are ignored. `fvg_ob_long` on 8000 bars now spans 11 months and 61 trades, against 8 before. Multiple-comparisons policy agreed with the trader: pre-registered rule set, rolling walk-forward folds, «no edge» is a publishable result |
| **P2-4** | Journal pattern analysis (`journal analyze`, LLM error detection) | M | pending |

## P3–P5 — Feature work (gated on P1–P2)

| Item | Notes | Status |
|---|---|---|
| P3 | **1h3m Bellissimo formalised.** First of the trader's own setups encoded (`backtest/rules_bellissimo.py`, 6 arms: long/short × fta_or_skip / fta_or_liquidity, plus a 1W-filter arm). Required eight engine additions: `min_rr`, unfinished-trade counter, `Condition.value_ref` (compare two moving values across timeframes), `same_day`/`not_same_day` operators, `pool_ts` on sweep records, `invalidation_conditions` in the LTF scan, `tp_logic="fta_or_skip"`/`"fta_or_liquidity"`, `detect_previous_day_levels`. Also found and fixed: the rule evaluator cached detector results by name only, ignoring kwargs (same class as P0-9), and `1w` was missing from every timeframe table | ✅ DONE 2026-08-22 |
| P3 | **Significant-detector Pine overlay.** The LLM closes each analysis by calling `generate_pine_script` with the detectors that materially drove the verdict; the registry writes the overlay to `~/.trading-copilot/pine/` and returns a path. Pine emitters extracted from `scripts/debug_detectors.py` into `copilot/pine/` and shared by both paths (verified byte-identical for all 19 emitters). Carried the P0-9 fix with it | ✅ DONE 2026-08-22 |
| P3 | Chart `detect_cumulative_delta` as a layer — needs the delta fetch path plumbed into `generate_pine_script` (registry hands it a plain DataFrame today) | pending |
| P3 | Dashboard TUI (rich terminal) | blocked by P0–P1 |
| P3 | Multi-LLM provider abstraction | LOW — deferred |
| P4 | Screenshot / text trade analysis (multimodal) | blocked by P1-2 |
| P5 | More instruments (XAU → FX → indices); each = one `data/*.py` `DataSource`, detectors unchanged | blocked by stable crypto workflow |
| P5 | QoL: scheduled killzone reports, embeddings KB retrieval, report archive browser | deferred |

## Explicitly deferred
Order placement / broker APIs. Footprint imbalances & VWAP/TPO (L2/tick data unavailable on public REST).
Web/GUI frontend (REPL + TUI matches the discretionary workflow).

## Defects found during the strategy research (2026-08-23)

All found by running the research, not by reading the code. Each one produced
plausible numbers rather than an error, which is why they survived so long.

| # | Defect | Impact | Status |
|---|---|---|---|
| R-1 | LTF slices were unbounded (`_ltf_df.iloc[:cursor+1]`). `detect_bos` is superlinear: 2k bars 0.16 s → 100k bars 46.8 s, with an identical answer from 1000 bars on | One Bellissimo arm projected to ~13 h; actual 9.4 min after the fix | ✅ `_LTF_LOOKBACK_BARS = 3000` |
| R-2 | **Missing LTF data silently degraded the strategy.** On a fetch failure the engine logged "LTF entry will be skipped", then fell through to the HTF entry path and backtested a rule *without* its LTF confirmation, reporting plausible numbers for a different strategy | Any 429 mid-run silently invalidated the results | ✅ raises instead |
| R-3 | `detect_fractals` default `max_results=10` keeps the 10 most recent **in time**, but the target rule wants the nearest **in price** | 11 of 41 target resolutions changed; Bellissimo's short arm went from +0.361R to +0.065R once fixed | ✅ pool raised to 60, cache key includes it |
| R-4 | `--start/--end` sized the fetch to the window's own length, but the source returns the most recent N bars → the frame ended today and started *after* `start` | 15 Jun – 5 Aug was requested, 4 Jul – 5 Aug scanned; 4 of 5 trades lost | ✅ request reaches back from now |
| R-5 | LTF frame was fetched from "now" regardless of the HTF window | Date-ranged runs compared timeframes from different periods | ✅ `fetch_ohlcv_batched(end_ms=...)` |
| R-6 | `pd.Timestamp(aware_dt, tz="UTC")` raised on every date-ranged run | `--start/--end` had never worked at all | ✅ fixed |
| R-7 | HTF entry path never received the detector registry, and fed `None` targets straight into `compute_rr` | Detector-driven `tp_logic` silently resolved to None there; `nearest_fractal` crashed the run | ✅ fixed |
| R-8 | `fetch_ohlcv_batched` had no retry | First Binance 429 killed a run (and, via R-2, corrupted it instead) | ✅ backoff on 429/418/5xx |
| R-9 | Invalidation and entry conditions each recomputed the same detector on the same LTF bar | ~17% of runtime | ✅ shared `call_cache` |

| R-10 | An inverted stop (wrong side of entry) passed the R:R gate — `compute_rr` takes `abs(entry - sl)` | One trade booked at +11.88R, setting an arm's expectancy to +3.29R over 3 trades | ✅ `_stop_is_on_the_right_side` in both entry paths |
| R-11 | `_ltf_fvg_near_edge` sorted on `ts`/`timestamp`; the field is `formed_ts`, so it took the OLDEST zone | Limit entries rested on stale imbalances; test-arm trade counts were 3x too low | ✅ takes the first zone (list is newest-first) |

**Still open:** the LTF fetch is uncached, so every arm re-downloads ~95k bars
(64 requests); parallel arms need `-P 3` to stay under the rate limit.
