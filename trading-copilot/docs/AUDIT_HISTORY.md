# Audit History

Why the project went through two correction cycles in 2026, and what they found. The conventions that
came out of this are in [CONVENTIONS.md](CONVENTIONS.md); the live roadmap is in [../PLAN.md](../PLAN.md).
Full reports: [../REVIEW_2026-06-10.md](../REVIEW_2026-06-10.md) (system-wide),
[../DETECTOR_REVIEW_2026-06-10.md](../DETECTOR_REVIEW_2026-06-10.md) (all 23 tools, 19 probes),
[../REBASELINE_2026-06-10.md](../REBASELINE_2026-06-10.md) (first honest backtest numbers). Probe scripts
at [../probes/](../probes/); they are now encoded as `tests/test_probe_regression.py`.

## Course Correction #1 — May 2026

After building Phases 1–8, manual testing revealed fundamental issues with several core detectors.

**Root causes:**
1. **KB as sole algorithmic source of truth.** The KB explains *what concepts mean* well but does not
   provide rigorous, testable algorithms. Deriving detector logic from KB prose produced subjective,
   hard-to-debug implementations.
2. **No reference implementation.** Detectors were written in isolation without verifying against
   established SMC/ICT implementations; bugs accumulated silently.
3. **Tests verified code structure, not behavior.** Tests were written to match the implementation rather
   than assert known-correct outputs on explicit fixtures, so wrong implementations passed.

The May audit produced a detector table marking several detectors "fixed/rewritten." **It was superseded
by the June audit**, which showed several of those entries were still broken (`market_structure` wick-driven
flips, `detect_bos` missing textbook breaks, `detect_order_block` swing-dedup deleting the trigger swing).
The June verdicts below are authoritative.

## Course Correction #2 — June 2026 (authoritative)

### Headline findings
1. **Live analysis ran on the forming candle** — every detector treated a repaintable bar as closed.
2. **The backtest engine leaked future data** — LTF entries filled at pre-signal prices; HTF conditions
   evaluated the forming HTF bar; one-sided fees, no slippage, no funding. **All prior backtest numbers
   were invalid.**
3. **Detector probe score: 6 sound, 7 degraded, 10 broken** — and the broken set was what the prompt
   weighted most heavily (structure, OB, CD, absorption).
4. **The May P0 rewrites were never completed**, and the "281 green" suite included exactly the vacuous
   schema tests the conventions forbid — which is why the broken detectors passed.
5. **`smartmoneyconcepts` was declared "ground truth" but was not a dependency** — every detector was a
   hand-rolled reimplementation. Root cause of both cycles.

### June detector audit (supersedes the May table)

| Detector | Verdict | Probe evidence |
|---|---|---|
| `detect_fvg`, `detect_ifvg`, `detect_volume_profile`, `check_poc_location`, `check_price_in_lvn` | ✅ Works | Exact bounds / correct POC on known fixtures |
| `detect_fib_zones` | ⚠️ Long-only | No direction param → short OTE invisible |
| `detect_fractals` | ⚠️ Semantics | `is_swept` = any trade past level; conflates break with sweep |
| `check_multi_tf_alignment` | ⚠️ Incoherent | Two disjoint code paths; counter-trend labeled `aligned=true` |
| `current_killzone` | ⚠️ Weekend bug | Saturday 09:30 → active "London Open" killzone |
| `detect_rejection_block` | ⚠️ Doc mismatch | Fires without the body-engulf the docstring requires |
| `detect_mitigation_block`, `detect_sponsored_candle` | ⚠️ Wrong anchor | "Sweep" tested vs OB's own high/low, not a pool; old 2-candle OB predicate |
| `detect_market_structure` | ❌ Unreliable | HH/HL uptrend in pullback → `ranging`; 0.4% wick dip → `bearish` |
| `detect_bos` | ❌ Misses breaks | Textbook BOS (close above prior swing high) not emitted |
| `detect_order_block` | ❌ Misses the OB | Swing dedup deletes the broken swing → no OB; stale noise returned |
| `detect_liquidity` | ❌ False sweeps | Any wide bar crossing a swing high → "sweep, closed_back=true" |
| `detect_compression` | ❌ Noise | Compressions on random-walk charts; LRLR misinterpreted |
| `detect_cumulative_delta` | ❌ Both signals broken | Breakouts labeled sweeps; divergence only fires if the current bar is the extreme |
| `check_cd_absorption` | ❌ Wrong threshold | Volume 25% below average passes as "high volume" |
| `check_absorption_at_poi`, `check_cd_divergence_at_structure`, `check_ob_in_hvn` | ❌ Inherit parents | Composites of the broken detectors above |
| `detect_breaker_block` | ❌ Misses class | Demands an FVG as pierce evidence; plain close-through never flips |

The root causes R1–R5 distilled from this audit are documented in [CONVENTIONS.md](CONVENTIONS.md)
(Anti-patterns), since they are what the coding rules exist to prevent.

### Additional system bugs (from the system-wide review)
- `agent.py`: tool results keyed by name only → multi-TF results overwrite; duplicate assistant message
  per turn. (P1-3 — fixed 2026-06-19.)
- Backtest `tools_confirmed` recorded every evaluated detector (constant per rule) → tool ranking
  degenerate. `simulate._resolve_limit_level` picked `fvgs[0]`/`obs[0]` without a direction check.
  HTF condition cache key ignored kwargs → collisions; HTF fetch ignored backtest start/end.
- Inconsistent ATR definitions across modules; static ATR scalar in historical loops.
- `prompts.py` lacked the HTF-POI hard gate and conflict hierarchy, and instructed Claude to upgrade
  confidence on `confirmed_manipulation`/`absorption_detected`, both shown to be noise.

### Re-baseline outcome
After P0-1…P0-7 landed, all rules were re-run walk-forward with honest costs
([../REBASELINE_2026-06-10.md](../REBASELINE_2026-06-10.md)): **no rule showed a positive edge** on
BTCUSDT 1h / 2000 bars (best in-sample expectancy −0.015R; OOS samples ≤7 trades — too small to conclude).
The pre-fix positive numbers were artifacts of the look-ahead leak + one-sided fees. This narrow run is a
smoke test, not a verdict — multi-TF setups across years of data (split by week/month) are the real test
of whether edge exists. Rule R&D restarts from this honest baseline.
