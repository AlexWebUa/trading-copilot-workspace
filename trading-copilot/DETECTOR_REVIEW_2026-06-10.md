# Detector Review — all 23 tools, code + empirical probes
_2026-06-10 · Method: full code read of `copilot/detectors/` plus 19 synthetic-fixture probes with known ground truth. Probe scripts are committed at [probes/probe_detectors.py](probes/probe_detectors.py) and [probes/probe_detectors2.py](probes/probe_detectors2.py) — rerun with `python probes/probe_detectors.py`._

## Verdict table

| Detector | Verdict | Probe evidence |
|---|---|---|
| `detect_fvg` | ✅ **Works** | Exact bounds on known gap (101–103) ✓ |
| `detect_ifvg` | ✅ **Works** | Pierced FVG correctly flips polarity ✓ |
| `detect_volume_profile` | ✅ **Works** (approximation) | POC lands in the known high-volume area ✓ |
| `check_poc_location`, `check_price_in_lvn` | ✅ Thin VP wrappers, fine | — |
| `detect_rejection_block` | ⚠️ Doc/logic mismatch | Fires without the body-engulf its docstring requires; also not the ICT "rejection block" (which is wick-based) |
| `detect_fib_zones` | ⚠️ **Long-only** | Price at the textbook *short* OTE → `in_ote=false`; no direction parameter exists |
| `detect_fractals` | ⚠️ Semantics | `is_swept` = "any later trade past it" — conflates close-through *break* with wick *sweep*; contradicts `detect_liquidity`'s definition |
| `check_multi_tf_alignment` | ⚠️ Incoherent output | LTF ranging → `role=unclear` + `quality=weak` + `aligned=false` from two disjoint code paths; counter-trend LTF labeled `aligned=true, strong` |
| `current_killzone` | ⚠️ Weekend bug | Saturday 09:30 reported as active "London/Kyiv Open" killzone |
| `detect_mitigation_block` | ⚠️ Proxy semantics | "No prior sweep" tested against the OB's *own low*, not a liquidity level; built on the old 2-candle OB predicate |
| `detect_sponsored_candle` | ⚠️ Wrong anchor | Detects the pattern, but the "sweep" is any dip below the OB's own low that recovers — not a sweep of a *prior liquidity pool*; May audit's rewrite (sweep candle = OB) never done |
| `detect_market_structure` | ❌ **Unreliable bias** | Clean HH/HL uptrend in a pullback → `ranging`; one more red bar (0.4% wick dip) → `bearish`. State is wick-driven at the right edge |
| `detect_bos` | ❌ Misses breaks | Textbook bullish BOS (close above 102) not emitted; returns noise-level cBOS events instead |
| `detect_order_block` | ❌ **Misses the OB** | Textbook swing-break OB: the broken swing (105) is deleted by swing dedup, no OB created; a stale OB from pre-trend noise returned as the active POI |
| `detect_liquidity` | ❌ False sweep labels | Wide bullish bar crossing a swing **high** → reported as "**sellside** sweep, closed_back=true" of that high. Genuine wick sweeps do work ✓, but every wide-range bar crossing any level generates a wrong-side sweep |
| `detect_compression` | ❌ Pure noise | "Compressions" found on **50/50** random-walk charts. Also: LRLR means Low Resistance Liquidity Run in SMC, not "lower range lower range" — wrong concept entirely |
| `detect_cumulative_delta` | ❌ Both signals broken | (1) Breakout bar with 0.7% wick + strongly positive delta → labeled `sweep_confirmation` (it's a breakout, not a sweep; close-back never checked). (2) Real swing-to-swing bearish divergence two bars old → `divergences=[]` (only fires if the *current* bar is the extreme) |
| `check_cd_absorption` | ❌ Wrong threshold, wrong name | Bar with volume **25% below average** → `absorption_detected=true` (threshold is `vol ≥ 0.7×avg`). Bullish-only (close near high); contains no CD despite the name |
| `check_absorption_at_poi` | ❌ Inherits both parents | Broken absorption gate × broken OB detector; `reversal_direction` can be "bearish" while the absorption signature is bullish-only |
| `check_cd_divergence_at_structure` | ❌ Inherits three parents | Broken divergence logic × unstable market_structure × `sweep_preceded` = "any sweep in last 30 bars" with no level/side relevance check |
| `check_ob_in_hvn` | ❌ Inherits OB | Overlap math is fine, but it grades whichever OB the broken detector returns |
| `detect_breaker_block` | ❌ Misses the class | OB closed through by overlapping candles (no FVG) → no breaker. Code demands an FVG as pierce evidence — not the SMC definition. Also built on the old OB predicate, so its OB universe differs from `detect_order_block`'s |
| `generate_pine_script` | ⚠️ Mechanical | Works as plumbing; chart quality is bounded by the detectors above |

Score: **6 sound, 7 degraded, 10 broken or misleading.** The broken set includes the detectors your prompt weights most heavily (structure, OB, CD, absorption).

---

## Five root causes explain almost everything

**R1. Swing dedup deletes broken swings (`market_structure._deduplicate_swings`).**
When price breaks a swing high and rallies to a new confirmed high before any intervening swing low confirms, dedup sees two consecutive "high" swings and keeps only the higher one — retroactively erasing the very swing whose break defines the OB/BOS. Debug trace from the probe: raw swings contain `high@8 = 105`, dedup output is `[..., low@7, high@13 = 106.8]` — the 105 swing is gone, so `detect_order_block` never triggers and `detect_bos` never emits the break. This is not how smc.py works: there, break detection consumes swings chronologically; dedup-then-scan loses information. **Affects: order_block, bos, market_structure, and everything downstream (ob_in_hvn, absorption_at_poi).**

**R2. Right-edge synthetic swing makes "state" wick-driven.**
`_add_boundary_swings` plants a synthetic swing at the last bar using that bar's high/low. The state machine then requires the *current bar* to exceed the prior swing for "bullish" — so every ordinary pullback reads `ranging`, and a 0.4% wick below the prior pullback low flips the state to `bearish` with no close confirmation. Your D1/H4/H1 bias — the foundation of the whole protocol — oscillates bar to bar. Combined with the forming-bar issue (see REVIEW_2026-06-10.md §A1), live bias can flip *intra-candle*.

**R3. Two competing OB definitions.**
`detect_order_block` was rewritten to swing-break (correct direction), but `breaker_block`, `mitigation_block`, and `sponsored_candle` still use the old 2-candle `is_bullish_ob` predicate from `utils.py`. The OB a breaker "inverts" may never have existed per `detect_order_block`. One concept, two universes, drawn on the same Pine chart.

**R4. "Sweep" anchored to the wrong level.**
sponsored_candle and mitigation_block test sweeps against the OB's *own* high/low; liquidity's sweep scanner tests every pool against both sides geometrically, producing wrong-side labels ("sellside sweep" of a swing high). A sweep is the taking of a *liquidity pool* (prior swing/EQH/EQL/session extreme) — none of the sweep checks reference one.

**R5. Last-bar-only comparisons.**
CD divergence, sweep confirmation, and absorption all examine only the final bar against fixed lags or averages, with thresholds that were never validated (`wick > 0.2% of range`, `volume ≥ 0.7× average`). They fire constantly or miss the textbook case, in both directions.

---

## What this means in practice

The prompt (`prompts.py`) instructs Claude: *"if `confirmed_manipulation=true`, this is the HIGHEST-QUALITY reversal signal — upgrade confidence"* and *"absorption_detected=true → highest-quality entry signal."* The probes show both flags fire on ordinary breakouts and quiet below-average-volume bars. Today's reports therefore systematically upgrade confidence on noise, and the bias section flips with every retracement. The detectors that *do* work (FVG, IFVG, VP) are the ones whose reports you can currently trust.

## Recommended fix order

1. **Replace the swing/BOS/OB/liquidity stack with `smartmoneyconcepts`** (already your declared ground truth; not yet a dependency). This eliminates R1–R3 wholesale rather than patching a custom pipeline that has now failed two audits. Keep your JSON output contracts as thin wrappers.
2. **Delete or quarantine, don't ship:** `detect_compression`, `check_cd_absorption`, `check_absorption_at_poi`, `check_cd_divergence_at_structure`, and CD's `sweep_confirmation`/`divergences` fields. Until rewritten with validated thresholds, remove them from the MCP tool list and the prompt's orderflow rules — a missing signal is safer than a random one. Keep CD's `session_delta`/`delta_trend` (raw sums, trustworthy).
3. **Rewrite CD divergence swing-to-swing:** compare confirmed price pivots against CD values at those pivots (use the library's swings), not the last bar against lags.
4. **Fix sweep anchoring** (R4): sweeps must reference pools from `detect_liquidity` / prior swings, with the side determined by pool type. Add the pool-side check to `_find_sweeps` (one condition: only test buyside sweeps at buyside pools, and require the wick — not the open — to originate beyond the level).
5. **Small fixes:** direction parameter for `fib_zones` OTE; weekday gate in `current_killzone`; reconcile `multi_tf` into one code path with explicit semantics (`aligned` should not mean "LTF opposes HTF"); align `fractals.is_swept` with the close-back definition or rename to `is_taken`.
6. **Convert the probes into the regression suite.** The 19 probes in `probes/` are exactly the fixture-based tests your Working Rules mandate and the current test files lack. Each FAIL above should become a failing pytest before any fix, then green after.

One caution: I am not a financial advisor and nothing here validates the *strategy* — these findings are about whether the code measures what it claims to measure. Even with every detector correct, edge has to be demonstrated by the (fixed) backtester.
