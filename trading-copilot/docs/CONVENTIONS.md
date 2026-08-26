# Engineering Conventions

Rules that govern all development. They override any conflicting earlier conventions. Architecture lives
in [ARCHITECTURE.md](ARCHITECTURE.md); the roadmap in [../PLAN.md](../PLAN.md).

## Knowledge hierarchy for detector algorithms

```
1. Verified open-source implementations  ← PRIMARY
   ├── smartmoneyconcepts (github.com/joshyattridge/smart-money-concepts)
   │   MIT licensed, battle-tested. Algorithmic ground truth for:
   │   swing detection, BOS/CHoCH, OB, FVG, liquidity.
   └── TradingView community Pine Scripts (high-rating, verified)
       Visual ground truth. Our Pine Script output must match these visually.

2. Academic / quant market-microstructure resources  ← SECONDARY
   └── For concepts not covered above.

3. Knowledge base (../knowledge_base/)  ← TERTIARY
   ├── Use for: ICT terminology, concept interpretation, setup rules.
   └── Do NOT use as sole source for algorithm logic or numerical thresholds.
```

The root cause of both 2026 audit cycles was deriving detector logic from KB prose instead of a verified
implementation. Use `smartmoneyconcepts` as a real dependency, not a reference to reimplement.

## Detector development checklist

**Before writing code:**
- [ ] Find the algorithm in `smartmoneyconcepts` or a verified Pine Script.
- [ ] Understand it mechanically: exact conditions, thresholds, edge cases — the math, not the concept.
- [ ] Write 3+ test fixtures with explicitly known expected outputs *before* touching the implementation.

**After writing code:**
- [ ] `pytest` — all tests pass.
- [ ] Generate Pine Script — `scripts/debug_detectors.py --detector <name>` for the isolated view, or
      `generate_pine_script(detectors=[...])` for it in context — overlay on TradingView, compare visually.
      Both render through `copilot/pine/emitters.py`; a new detector needs an entry there plus one in
      `pine/runners.py`, and a line in `OVERLAY_LAYERS` if the copilot should be able to chart it.
- [ ] Only then merge.

## Test standards

Tests must assert **known behavior on explicitly constructed data**, not schema shape.

**Required per detector:** a positive case (pattern at a known price/bar → assert the specific value), a
negative case (no pattern → assert empty), and an edge case (insufficient bars, flat market, boundary).

**Forbidden:**
```python
assert "events" in result          # tests schema, not behavior
assert total >= 0                  # vacuous
result = detect_bos(real_btc_df)   # no known ground truth on a raw real-market DF
assert result["events"][0]["type"] == "BOS"
```
**Right:**
```python
df = make_explicit_hh_hl_df()      # Low@100→High@110→Low@105→High@115
result = detect_bos(df, swing_lookback=3)
assert any(e["type"] == "BOS" and abs(e["broken_level"] - 110) < 1 for e in result["events"])
```

**Probes are the regression suite.** Every bug found by `probes/*.py` is a test in
`tests/test_probe_regression.py`. A bug whose fix has not landed is `xfail(strict=True)` with a `reason`
citing the PLAN item — it goes green (XPASS, failing the suite) the moment the fix lands, forcing removal
of the marker. Use the same pattern for any known-broken-detector test.

## Coding rules

- **Never analyze the forming candle.** `normalize_binance` drops the last kline when its
  `close_time > now` (`include_forming=False` default).
- **No static ATR scalars in historical loops.** Always per-bar: `atr_arr = (...).rolling(14).mean()`,
  index `atr_arr[i]`. Use the unified true-range definition (`smc_lib.true_range_atr`).
- **No string timestamps in internal computation.** Use integer `idx` (DataFrame position) throughout;
  convert to ISO 8601 only in the final output dict.
- **Swing detection deduplicates** to strict H-L-H-L alternation (`_deduplicate_swings`). But **break
  detection consumes swings chronologically** — deduplication must never erase a swing that was
  structurally broken (R1). No dedup-then-scan pipelines.
- **Single swing utility.** All detectors call `_find_raw_swings` + `_deduplicate_swings` from
  `market_structure.py`. No duplicate implementations elsewhere.
- **Sweeps reference liquidity pools, with side semantics.** A buyside sweep can only occur at a buyside
  pool (swing high / EQH / session high); the wick must originate beyond the level and close back inside
  (R4). Sweep side comes from pool type, not bar geometry.
- **Divergence/absorption compares confirmed pivots**, not the last bar against fixed lags or averages.
  Every numeric threshold needs a probe demonstrating it separates signal from noise (R5).
- **Backtests use no data from after the decision moment.** LTF scans start at signal-bar *close*; HTF
  slices include only HTF bars whose *close* ≤ current bar close. Fees two-sided; model slippage and
  funding.
- **Fail soft / compact output** as in [ARCHITECTURE.md](ARCHITECTURE.md) design principles.

## Anti-patterns — root causes from the audits (R1–R5)

These are the specific failure modes the rules above prevent. Detector work must not reintroduce them.

- **R1 — Swing dedup deletes broken swings.** Merging consecutive same-type swings *before* break scanning
  erases the swing whose break defines the OB/BOS. Consume swings chronologically instead. (Affects
  order_block, bos, market_structure and all downstream composites.)
- **R2 — Right-edge synthetic swing makes state wick-driven.** Planting the last bar's high/low as a swing
  makes "bullish" require the current bar to exceed the prior swing → every pullback reads `ranging`, wick
  dips flip to `bearish` with no close confirmation. Don't report the right-edge synthetic swing.
- **R3 — Competing OB definitions.** order_block uses swing-break; breaker/mitigation/sponsored historically
  used a 2-candle predicate — two OB universes on one chart. Rebuild all OB consumers on the single
  library/swing-break OB.
- **R4 — Sweeps anchored to the wrong level.** Sweep checks referencing the OB's own boundary or any level
  geometrically, never a liquidity pool with side semantics.
- **R5 — Last-bar-only comparisons with unvalidated thresholds.** CD divergence/sweep and absorption
  examining only the final bar against lags/averages (`wick > 0.2% of range`, `vol ≥ 0.7×avg`).
