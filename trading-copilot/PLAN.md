# Trading Co-Pilot — Implementation Plan

## Context

The user is a discretionary SMC/ICT trader with a complete, structured Obsidian KB at [knowledge_base/](knowledge_base/). Goal: build a Python system where **Claude (via Anthropic SDK) reads the KB as narrative context, then calls algorithmic detectors over OHLC data as tools** to produce a structured market analysis that the trader acts on manually.

**Why this shape.** The KB already encodes the "what to think" (concepts, setups, entry models, global rules). What the LLM cannot do alone is reliably measure things on a chart — fractal sweeps, FVG fill depth, OB mitigation state, multi-TF confluence. Detectors close that gap by returning **compact, self-describing JSON** the LLM can reason over without hallucinating candle positions.

**Decisions locked from the kickoff:**
- LLM backend: Anthropic SDK primary (Sonnet 4.6 default). Multi-LLM abstraction deferred — low priority while Claude performs well.
- Instruments v1: **crypto only (BTC, ETH)** via Binance public REST. Data layer kept pluggable so XAU/USD, EUR/USD, GER40/EU50, NAS100/SP500 can be added later.
- Interface: **interactive REPL/chat** in the terminal. Multi-turn conversation, session persistence.

**Hard constraints:**
- No order placement. Analysis only.
- Detectors pure-functional, unit-testable against fixture OHLC (no live API dependency in tests).
- Multi-TF is non-negotiable: D1 → H4 → H1 → M15 → M3/M1 is how the user thinks, and the system must mirror it.
- Session-awareness: OTT window 09:00–17:00 Kyiv, killzones at 09:00 / 15:00 / 17:00 Kyiv; NY AM/PM windows for indices (later).

---

## Course Correction — May 2026

After building Phases 1–8, manual testing revealed fundamental issues with several core detectors. This section documents the lessons learned and the corrected approach going forward.

### Root causes

**1 — KB as sole algorithmic source of truth.** The knowledge base contains conceptual explanations written through the lens of personal understanding. It is excellent for *what concepts mean* and *how to interpret signals*, but it does not provide rigorous, testable algorithms. Deriving detector logic directly from KB prose produced subjective, hard-to-debug implementations.

**2 — No reference implementation.** Detectors were written in isolation without verifying against established SMC/ICT implementations. Bugs accumulated silently until manual chart comparison exposed them months later.

**3 — Tests verified code structure, not behavior.** Tests were written to match the implementation rather than assert known-correct outputs on explicitly constructed fixtures. When the implementation was wrong, the tests passed anyway.

### Detector audit results (May 2026)

| Detector | Manual Test | Action |
|---|---|---|
| `detect_fvg` | ✅ Correct | Enhanced — `join_consecutive=True` added (merges multi-candle impulse gaps per smc.py) |
| `detect_ifvg` | ✅ Correct | Keep |
| `detect_volume_profile` | ✅ Correct | Keep |
| `current_killzone` | ✅ Correct | Keep |
| `detect_fractals` | ✅ Correct | Keep |
| `detect_order_block` | ✅ Rewritten | Swing-break algorithm per smc.py §ob — trigger on swing high/low break, OB = lowest-low (bullish) / highest-high (bearish) in window |
| `detect_rejection_block` | ✅ Correct | Keep |
| `detect_mitigation_block` | ✅ Correct | Keep |
| `detect_breaker_block` | ✅ Correct | Keep |
| `detect_market_structure` | ✅ Fixed | `_add_boundary_swings()` added — mirrors smc.py boundary logic; in-progress edge leg now included in 4-swing window |
| `detect_liquidity` | ⚠️ Partial | Rewrite — `is_swept` logic incorrect (trades-above ≠ sweep) |
| `detect_cumulative_delta` | ⚠️ Partial | Fix — divergence and sweep detection thresholds flawed |
| `detect_compression` | ❓ Uncertain | Rewrite — volatility squeeze ≠ trending LRLR concept |
| `detect_bos` | ✅ Fixed | 4-swing window algorithm per smc.py §bos_choch; returns `events` list (newest-first), not a single event |
| `detect_sponsored_candle` | ❌ Wrong | Rewrite — looks for OB+prior_sweep; should be sweep_candle=OB |

> ⚠️ **SUPERSEDED by the June 2026 audit** (see [Course Correction #2](#course-correction-2--june-2026) below).
> Empirical probes showed several "✅ Fixed/Rewritten" entries above are still broken:
> `detect_market_structure` (wick-driven state flips), `detect_bos` (misses textbook breaks),
> `detect_order_block` (swing dedup deletes the trigger swing). The June table is authoritative.

### Module status

| Module | Status | Notes |
|---|---|---|
| `data/` | ❌ Fix (June 2026) | Forming (incomplete) Binance candle kept in every DataFrame — all live signals repaint. Drop last bar when `close_time > now` |
| `kb/` | ✅ Keep | Works correctly |
| `mcp_server.py` + registry | ⚠️ Trim | Architecture sound; quarantine broken orderflow tools from tool list (see June audit) |
| `cli.py`, `session.py` | ✅ Keep | Works correctly |
| `llm/agent.py`, `tools.py` | ⚠️ Fix (June 2026) | Tool results keyed by name only — multi-TF results overwrite each other, corrupting state diff; duplicate assistant message appended per turn |
| `llm/prompts.py` | ❌ Update | P1 workflow revision still pending; orderflow rules currently instruct Claude to upgrade confidence on signals the June probes showed are noise |
| `llm/state.py` | ⚠️ Update | Field names change with detector rewrites; update in sync |
| `journal/` | ✅ Keep | Unit-tested; validate with real trade data |
| `stats/` | ⚠️ Caveat | `tools_confirmed` in backtest records lists every evaluated detector (constant per rule) → tool-effectiveness Δwinrate ranking is meaningless on backtest data |
| `backtest/` | ❌ Fix (June 2026) | Look-ahead leaks (LTF entry before signal close; forming HTF bar in HTF conditions); one-sided fee model; HTF cache ignores kwargs. All existing backtest numbers invalid |
| `detectors/pine_script.py` | ✅ Done | Mechanical plumbing OK; chart quality bounded by detector correctness |
| `scripts/debug_detectors.py` | ✅ Done | All per-detector Pine Script generators migrated to B&W design system |

---

## Course Correction #2 — June 2026

Full reports: [REVIEW_2026-06-10.md](REVIEW_2026-06-10.md) (system-wide) and [DETECTOR_REVIEW_2026-06-10.md](DETECTOR_REVIEW_2026-06-10.md) (all 23 tools, 19 empirical probes). Probe scripts committed at [probes/](probes/) — rerun with `python probes/probe_detectors.py`.

### Headline findings

1. **Live analysis runs on the forming candle.** `normalize_binance()` keeps Binance's incomplete last kline; no code drops it. Every detector treats a repaintable bar as closed — violates the "entry only on candle CLOSE" rule system-wide.
2. **The backtest engine leaks future data.** LTF entries can fill at prices from before the signal bar closed (`_find_ltf_idx` seeds at signal-bar *open*); HTF conditions evaluate the forming HTF bar (`index <= current_bar_ts` on open-time-indexed bars). Plus one-sided fees (docs say per-side), no slippage, no funding. **All existing backtest numbers are invalid.**
3. **Detector probe score: 6 sound, 7 degraded, 10 broken** — and the broken set is what the prompt weights most heavily (structure, OB, CD, absorption).
4. **The May P0 rewrites were never completed**, and the test suite that shows 281 green includes exactly the vacuous schema tests the Working Rules forbid (`assert total >= 0`), which is why the broken detectors pass.
5. **`smartmoneyconcepts` is declared "algorithmic ground truth" but is not in pyproject.toml** — every detector is a hand-rolled reimplementation. This is the root cause of both audit cycles.

### June detector audit (authoritative — supersedes May table)

| Detector | Verdict | Probe evidence |
|---|---|---|
| `detect_fvg`, `detect_ifvg`, `detect_volume_profile`, `check_poc_location`, `check_price_in_lvn` | ✅ Works | Exact bounds / correct POC on known fixtures |
| `detect_fib_zones` | ⚠️ Long-only | No direction param → short OTE invisible (`in_ote=false` at textbook short OTE) |
| `detect_fractals` | ⚠️ Semantics | `is_swept` = any trade past level; conflates break with sweep |
| `check_multi_tf_alignment` | ⚠️ Incoherent | Two disjoint code paths; LTF ranging → mixed verdicts; counter-trend labeled `aligned=true` |
| `current_killzone` | ⚠️ Weekend bug | Saturday 09:30 → active "London Open" killzone |
| `detect_rejection_block` | ⚠️ Doc mismatch | Fires without the body-engulf the docstring requires; not ICT's wick-based rejection block |
| `detect_mitigation_block`, `detect_sponsored_candle` | ⚠️ Wrong anchor | "Sweep" tested vs the OB's own high/low, not a liquidity pool; old 2-candle OB predicate |
| `detect_market_structure` | ❌ Unreliable | HH/HL uptrend in pullback → `ranging`; 0.4% wick dip → `bearish`. Wick-driven right-edge state |
| `detect_bos` | ❌ Misses breaks | Textbook BOS (close above prior swing high) not emitted; noise cBOS returned instead |
| `detect_order_block` | ❌ Misses the OB | Swing dedup deletes the broken swing when price rallies before a pullback confirms → no OB; stale noise zone returned |
| `detect_liquidity` | ❌ False sweeps | Any wide bar crossing a swing high → "sellside sweep, closed_back=true" of that high. (Genuine wick sweeps do register) |
| `detect_compression` | ❌ Noise | Compressions on 50/50 random-walk charts; LRLR = Low Resistance Liquidity Run, not "lower range lower range" |
| `detect_cumulative_delta` | ❌ Both signals broken | Breakouts labeled sweeps (no close-back check, wick threshold 0.2% of range); divergence only fires if the current bar is the extreme |
| `check_cd_absorption` | ❌ Wrong threshold | Volume 25% *below* average passes as "high volume" (`≥0.7×avg`); bullish-only; no CD despite name |
| `check_absorption_at_poi`, `check_cd_divergence_at_structure`, `check_ob_in_hvn` | ❌ Inherit parents | Composites of the broken detectors above |
| `detect_breaker_block` | ❌ Misses class | Demands an FVG as pierce evidence; plain close-through never flips to breaker |

### Root causes (R1–R5)

- **R1 — Swing dedup deletes broken swings.** `_deduplicate_swings` merges consecutive same-type swings *before* break scanning, erasing the swing whose break defines the OB/BOS. smc.py consumes swings chronologically instead. Affects order_block, bos, market_structure and all downstream composites.
- **R2 — Right-edge synthetic swing makes state wick-driven.** `_add_boundary_swings` plants the last bar's high/low as a swing; "bullish" then requires the current bar to exceed the prior swing → every pullback reads `ranging`, wick dips flip to `bearish` with no close confirmation.
- **R3 — Two competing OB definitions.** order_block uses swing-break; breaker/mitigation/sponsored still use the old 2-candle `is_bullish_ob` predicate — two OB universes on one chart.
- **R4 — Sweeps anchored to the wrong level.** Sweep checks reference the OB's own boundary or any level geometrically, never a liquidity pool with side semantics.
- **R5 — Last-bar-only comparisons with unvalidated thresholds.** CD divergence/sweep and absorption examine only the final bar against lags/averages (`wick > 0.2% of range`, `vol ≥ 0.7×avg`).

### Additional system bugs (from REVIEW_2026-06-10.md)

- `agent.py`: tool results keyed by name only → multi-TF results overwrite; duplicate assistant message per turn.
- Backtest `tools_confirmed` = every evaluated detector (constant per rule) → tool ranking degenerate.
- `simulate._resolve_limit_level` picks `fvgs[0]`/`obs[0]` without direction check.
- `fetch_ohlcv_with_delta` bypasses cache and injected DataSource.
- HTF condition cache key ignores kwargs → collisions; HTF fetch ignores backtest start/end range.
- Inconsistent ATR definitions across modules (high−low rolling mean vs true range); static ATR scalar in historical loops (violates own rule).
- `llm/prompts.py` lacks the protocol's HTF-POI hard gate, `## HTF POI` section, and conflict hierarchy — and instructs Claude to upgrade confidence on `confirmed_manipulation`/`absorption_detected`, both shown to be noise.

---

## Working Rules

These rules govern all future development. They replace any conflicting earlier conventions.

### Knowledge hierarchy for detector algorithms

```
1. Verified open-source implementations  ← PRIMARY
   ├── smartmoneyconcepts (github.com/joshyattridge/smart-money-concepts)
   │   MIT licensed, battle-tested, widely used in algo trading.
   │   Algorithmic ground truth for: swing detection, BOS/CHoCH, OB, FVG, liquidity.
   └── TradingView community Pine Scripts (high-rating, verified scripts)
       Visual ground truth. Our Pine Script output must match these visually.

2. Academic / quant resources on market microstructure  ← SECONDARY
   └── For concepts not covered by the above.

3. Knowledge base (knowledge_base/)  ← TERTIARY
   ├── Use for: ICT-specific terminology, concept interpretation, setup rules.
   └── Do NOT use as sole source for algorithm logic or numerical thresholds.
```

### Detector development checklist

Before writing code:
- [ ] Find algorithm in `smartmoneyconcepts` or a verified Pine Script
- [ ] Understand it mechanically: exact conditions, thresholds, edge cases — not the concept, the math
- [ ] Write 3+ test fixtures with explicitly known expected outputs before touching implementation

After writing code:
- [ ] Run `pytest` — all tests pass
- [ ] Generate Pine Script via `generate_pine_script`, overlay on TradingView, compare visually
- [ ] Only then merge

### Test standards

Tests must assert **known behavior on explicitly constructed data**, not just schema shape.

**Required per detector:**
- Positive case: fixture with pattern at known price/bar — assert the specific value
- Negative case: fixture without the pattern — assert empty result
- Edge case: insufficient bars, flat market, boundary condition

**Forbidden:**
```python
# WRONG — tests schema, not behavior
assert "events" in result

# WRONG — asserts on arbitrary real-market DF without known ground truth
result = detect_bos(real_btc_df)
assert result["events"][0]["type"] == "BOS"

# RIGHT — explicitly constructed fixture with known expected output
df = make_explicit_hh_hl_df()   # Low@100→High@110→Low@105→High@115
result = detect_bos(df, swing_lookback=3)
assert any(e["type"] == "BOS" and abs(e["broken_level"] - 110) < 1 for e in result["events"])
```

### Coding rules

- **No static ATR scalars in historical loops.** Always `atr_arr = (...).rolling(14).mean().values`, index per bar: `atr_arr[i]`.
- **No string timestamps in internal computation.** Use integer `idx` (DataFrame position) throughout. Convert to ISO 8601 string only in the final output dict.
- **Swing detection must deduplicate.** Any function returning swing highs/lows must ensure strict H-L-H-L alternation via `_deduplicate_swings()`. No two consecutive same-type swings allowed.
- **Single swing utility.** All detectors using swing points call `_find_raw_swings` + `_deduplicate_swings` from `market_structure.py`. No duplicate implementations in other files.
- **Fail soft.** Never raise for "nothing found." Return `{"status": "none"}` or empty list with `"count": 0`.
- **Compact output.** Return 3–10 most recent/relevant objects. LLM context is finite.

Added June 2026 (from Course Correction #2):

- **Never analyze the forming candle.** `normalize_binance` must drop the last kline when its `close_time > now` (`include_forming=False` default).
- **Use `smartmoneyconcepts` as a real dependency**, not a reference to reimplement. Swings, BOS/CHoCH, OB, FVG, liquidity = thin wrappers converting library output to our JSON contracts. Custom code only for concepts the library lacks (killzones, sponsored candle, multi-TF, composites).
- **No dedup-then-scan swing pipelines.** Break detection must consume swings chronologically; deduplication must never erase a swing that was structurally broken (R1).
- **Sweeps reference liquidity pools, with side semantics.** A buyside sweep can only occur at a buyside pool (swing high/EQH/session high), wick must originate beyond the level, close-back required (R4).
- **Divergence/absorption logic compares confirmed pivots, not the last bar** against fixed lags or averages. Every numeric threshold needs a probe demonstrating it separates signal from noise (R5).
- **Backtests: no data from after the decision moment.** LTF scans start at signal-bar *close*; HTF slices include only HTF bars whose *close* ≤ current bar close. Fees two-sided; model slippage and funding.
- **Probes are the regression suite.** Every bug found by `probes/*.py` becomes a failing pytest before the fix, green after. Schema-shape tests (`assert "x" in result`, `assert total >= 0`) are forbidden and existing ones must be replaced.

---

## Project structure

```
trading-copilot/
├── pyproject.toml              # uv/pip, Python 3.11+
├── README.md
├── .env.example                # ANTHROPIC_API_KEY, cache dir, log level
├── config.toml                 # default symbols, TFs, killzone times, model IDs
│
├── copilot/
│   ├── __init__.py
│   ├── cli.py                  # entry point: `python -m copilot` → REPL
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── base.py             # DataSource protocol
│   │   ├── binance.py          # Binance klines fetcher
│   │   ├── cache.py            # parquet disk cache, TTL per TF
│   │   └── normalize.py        # DataFrame schema: [ts, open, high, low, close, volume], UTC index
│   │
│   ├── detectors/
│   │   ├── __init__.py
│   │   ├── types.py            # TypedDicts for detector return shapes
│   │   ├── market_structure.py
│   │   ├── fractals.py
│   │   ├── bos.py
│   │   ├── fvg.py
│   │   ├── order_block.py
│   │   ├── liquidity.py        # EQH/EQL, recent swing highs/lows, sweeps
│   │   ├── fib_zones.py        # premium/discount, OTE
│   │   ├── sessions.py         # killzone/OTT helpers — not a detector, but lives here
│   │   └── multi_tf.py         # htf/ltf confluence checker
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── tools.py            # registry: detector fn → Anthropic tool schema
│   │   ├── agent.py            # tool-use loop
│   │   ├── prompts.py          # system prompt templates
│   │   └── report.py           # final structured report rendering
│   │
│   ├── kb/
│   │   ├── __init__.py
│   │   ├── loader.py           # reads markdown, parses frontmatter
│   │   └── selector.py         # picks which notes to inject for a given query
│   │
│   └── session.py              # REPL state: symbol, TFs, last analysis, transcript
│
└── tests/
    ├── fixtures/
    │   ├── btc_1h_trend.parquet
    │   ├── btc_15m_sweep.parquet
    │   └── …                   # ~6 hand-curated setups
    ├── test_detectors_fvg.py
    ├── test_detectors_bos.py
    ├── test_detectors_ob.py
    ├── test_detectors_ms.py
    ├── test_detectors_liquidity.py
    └── test_agent_loop.py      # mocks Anthropic; verifies tool-dispatch correctness
```

Rationale: `detectors/` and `data/` are the core; everything else is thin glue. Each detector is **one file, one concept, one pure function** — easy to test, easy to add new ones.

---

## Data layer

### Fetch & normalize

`copilot/data/binance.py` hits `/api/v3/klines` (public, no auth, generous rate limits). Returns a canonical pandas DataFrame:

```python
# copilot/data/normalize.py
SCHEMA = ["open", "high", "low", "close", "volume"]

def normalize(raw: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(raw, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", *["_"] * 5,
    ])
    df = df[["open_time", *SCHEMA]].astype({c: "float64" for c in SCHEMA})
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.set_index("ts")[SCHEMA]
```

**All detectors accept this DataFrame.** No raw lists, no other shapes. Fixtures use the same schema.

### Cache

Parquet files keyed by `(exchange, symbol, tf, start, end)` in `~/.cache/trading-copilot/`. TTL:
- 1m/3m: 60s
- 15m/1h: 5min
- 4h/1d: 1h

Stale closed bars never refetch; only the last (forming) bar is revalidated.

### Multi-TF

`fetch_multi_tf(symbol, tfs=["1d", "4h", "1h", "15m", "3m"], bars_per_tf=500)` returns `dict[str, pd.DataFrame]`. All detectors operate on a single TF at a time; cross-TF logic lives in `detectors/multi_tf.py`.

### Pluggability

```python
# copilot/data/base.py
class DataSource(Protocol):
    def get_ohlc(self, symbol: str, tf: str, bars: int) -> pd.DataFrame: ...
    def supports(self, symbol: str) -> bool: ...
```

Binance is the first impl. Adding a new source = new file implementing the protocol + a line in a registry. No other code moves.

---

## Detector library

### Design principles

1. **Pure function.** Input: DataFrame + params. Output: JSON-serializable dict. No hidden state, no I/O.
2. **Compact output.** Return the 3–10 most recent / most relevant objects, not every historical match. LLM context is finite.
3. **Self-describing fields.** Field names readable without docstrings (`is_mitigated`, not `mit`; `fill_percentage`, not `fp`).
4. **No floats longer than 2 decimals.** Use the instrument's tick size; store `price`, `upper`, `lower` at rounded precision.
5. **Timestamps as ISO 8601 UTC strings in the JSON output.** pandas Timestamps don't round-trip cleanly through Anthropic tool results.
6. **Fail soft.** Empty result → `{"status": "none", "reason": "..."}`. Never raise for "nothing found".

### Tier A — ship in Phase 1

These are the minimum the LLM needs to reconstruct a market picture. Each gets its own module + test file.

#### `detect_market_structure(df, swing_lookback=5) -> dict`
Fractal-based swing detection, state machine over HH/HL vs LH/LL.
Algorithm mirrors `smc.py §swing_highs_lows + bos_choch`. Key addition: `_add_boundary_swings()` plants synthetic opposite-type swings at bar 0 and bar n-1 so the in-progress edge leg is always included in the 4-swing analysis window.
```python
{
  "state": "bullish" | "bearish" | "ranging",
  "last_swing_high": {"price": 67234.5, "ts": "2026-04-18T14:00:00Z"},
  "last_swing_low":  {"price": 66112.0, "ts": "2026-04-18T09:00:00Z"},
  "bars_in_state": 42,
  "last_bos_type": "BOS" | "cBOS" | null,
  "current_price": 67500.0,
  "atr_14": 210.5
}
```

#### `detect_bos(df, swing_lookback=5, max_results=5) -> dict`
Scans every 4-swing window `[A, B, C, D]` for BOS / cBOS, matching `smc.py §bos_choch`.
Returns a **list** of events newest-first; does NOT return a single event any more.
```python
{
  "events": [
    {
      "type": "BOS" | "cBOS",
      "direction": "bullish" | "bearish",
      "broken_level": 67234.5,
      "break_ts": "2026-04-18T15:00:00Z",
      "break_candle_body_atr": 2.4
    },
    ...
  ],
  "count": 2,
  "latest_bias": "bullish" | "bearish" | "none"
}
```
- `BOS`  = break in trend direction (HL+HH or LH+LL) — continuation.
- `cBOS` = structural reversal (LL+HH or HH+LL) — Change of Character per smc.py.

#### `detect_fvg(df, min_width_atr=0.1, max_age_bars=200, join_consecutive=True) -> dict`
3-candle imbalance scan. Returns **active** (unfilled or partially filled) FVGs only.
`join_consecutive=True` (default) merges adjacent same-direction FVGs produced by a
multi-candle impulse into one wider zone — matches `smc.py fvg(join_consecutive=True)`.
```python
{
  "fvgs": [
    {
      "type": "bullish",
      "upper": 67100.0, "lower": 66950.0,
      "formed_ts": "2026-04-18T12:00:00Z",
      "fill_percentage": 0,
      "fill_state": "untouched" | "IOFED" | "CE_tagged" | "filled",
      "age_bars": 5,
      "width_atr_fraction": 0.72
    },
    …
  ],
  "count_active": 3
}
```
IOFED = touched ≥1% depth. CE_tagged = 50% depth. Filled → dropped from list unless inverted (see IFVG).

#### `detect_order_block(df, lookback=100, max_results=6, swing_lookback=5) -> dict`
Swing-break algorithm per `smc.py §ob`. OB is the **lowest-low** candle (bullish) or
**highest-high** candle (bearish) in the window `[swing_idx+1 .. breakout_bar-1]`,
where the trigger is a close that breaks a confirmed structural swing high or low.
Mitigation: 50% midpoint (CE). `has_fvg_after` remains the quality marker.
```python
{
  "obs": [
    {
      "type": "bullish",
      "high": 66980.0, "low": 66890.0,
      "formed_ts": "2026-04-18T11:00:00Z",
      "has_fvg_after": true,       # FVG immediately after OB candle = higher quality
      "is_mitigated": false,
      "distance_atr": 0.8,
      "age_bars": 14
    }
  ],
  "count": 2
}
```

#### `detect_liquidity(df, tolerance_atr=0.1) -> dict`
Equal highs/lows (EQH/EQL), recent swing pools, session highs/lows.
```python
{
  "buyside_liquidity": [
    {"price": 67500.0, "type": "EQH", "touches": 3, "last_touch_ts": "..."},
    {"price": 67420.0, "type": "swing_high", "age_bars": 18}
  ],
  "sellside_liquidity": [...],
  "recent_sweeps": [
    {"side": "buyside", "swept_level": 67500.0, "sweep_ts": "...", "closed_back": true}
  ]
}
```
"Swept" = wick pierced the level, then close returned inside. This is the LLM's signal for "liquidity taken".

#### `detect_fib_zones(df, swing_high, swing_low) -> dict`
Given a declared swing (LLM-picked or auto from MS), returns premium/discount/OTE.
```python
{
  "equilibrium": 66556.0,
  "premium_zone": {"upper": 67234.5, "lower": 66556.0},
  "discount_zone": {"upper": 66556.0, "lower": 66112.0},
  "ote": {"upper": 66840.0, "lower": 66733.0},
  "current_price_location": "premium" | "discount" | "equilibrium"
}
```

#### `check_multi_tf_alignment(htf_state, ltf_state) -> dict`
Not a chart detector — a **reconciliation helper** the LLM calls after fetching MS on two TFs.
```python
{
  "aligned": true,
  "htf_bias": "bullish",
  "ltf_role": "pullback" | "continuation" | "counter_trend",
  "sync_quality": "strong" | "weak" | "desync"
}
```
Implements the KB's RTO (reverse trade offset) rule.

### Tier B — Phase 2

Added when Tier A proves useful: IFVG (inverted FVG), Breaker Block, Mitigation Block, Rejection Block, Sponsored Candle, Compression/LRLR, Killzone state.

### Tier C — skip in v1

Volume-profile-dependent (POC, VA, Single Prints, VWAP), order-flow (SMT divergence, Inducement as subjective read). Can be added if/when a data source with tick/volume-profile data is wired in.

### Edge cases (codify as tests)

- Fewer bars than lookback → `{"status": "insufficient_data", "needed": N, "got": M}`.
- All-same-price bars (halted market) → skip, don't divide by zero.
- FVG formed across a session boundary → still valid; sessions tagged separately.
- Detector called with wrong TF string → raise early with available TFs listed.

---

## LLM integration layer

### Tool schema generation

Each detector has a companion tool spec. Keep them **co-located** with the detector — not in a mega-registry file — so adding a detector is a one-file change.

```python
# copilot/detectors/fvg.py
TOOL_SCHEMA = {
    "name": "detect_fvg",
    "description": (
        "Find active Fair Value Gaps (3-candle imbalances) on a given timeframe. "
        "Returns unfilled or partially filled FVGs with fill state. "
        "Use when you need to identify unmitigated inefficiencies as POIs."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "e.g. BTCUSDT"},
            "timeframe": {"type": "string", "enum": ["1m","3m","5m","15m","1h","4h","1d"]},
            "min_width_atr": {"type": "number", "default": 0.15},
            "max_age_bars": {"type": "integer", "default": 200}
        },
        "required": ["symbol", "timeframe"]
    }
}

def detect_fvg(df, min_width_atr=0.15, max_age_bars=200) -> dict: ...
```

`copilot/llm/tools.py` auto-discovers `TOOL_SCHEMA` and the callable from each `detectors/*.py` module via `pkgutil`. No manual registry maintenance.

Tool descriptions matter: **the description is what Claude reads to decide when to call it.** Phrase each in the form "Use when you need to [task]" so the selection heuristic is obvious.

### Agent loop

Standard Anthropic tool-use loop — multi-turn, bounded.

```python
# copilot/llm/agent.py (sketch)
def run_analysis(user_query: str, session: Session) -> AnalysisReport:
    messages = [{"role": "user", "content": user_query}]
    system = build_system_prompt(session)   # KB-injected, see below

    for turn in range(MAX_TURNS := 12):
        resp = client.messages.create(
            model=session.model,              # claude-sonnet-4-6 default
            system=system,
            tools=TOOL_REGISTRY.as_anthropic_tools(),
            messages=messages,
            max_tokens=4096,
        )
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            return parse_final_report(resp.content)

        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                result = TOOL_REGISTRY.dispatch(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })
        messages.append({"role": "user", "content": tool_results})

    raise AgentLoopBudgetExceeded(MAX_TURNS)
```

**Prompt caching:** mark the system prompt (KB + instructions) with `cache_control: {"type": "ephemeral"}`. The KB is large and stable across a REPL session — caching cuts cost 70–90% on follow-up turns.

**Multi-turn vs single-pass:** multi-turn. The user's mental model is iterative ("what's on H1? now zoom to M15. is there a sweep?"). A single-pass agent would either call too many detectors defensively (cost) or too few (shallow analysis). The REPL naturally caps scope per turn.

### KB injection strategy

Full KB is ~50–80 notes. Dumping all of it exceeds healthy context. Use **two-tier injection**:

1. **Always-injected core** (~5–8 notes): global rules, bias-template hierarchy, POI taxonomy, entry-model index. These are the "constitution" — the LLM needs them for every query. Source:
   - [_Global_Rules.md](knowledge_base/00_Index/_Global_Rules.md)
   - [_MOC.md](knowledge_base/00_Index/_MOC.md)
   - [01_Concepts/Multi_TF_Analysis.md](knowledge_base/01_Concepts/Multi_TF_Analysis.md)
   - [08_Entry_Models/Entry_Models.md](knowledge_base/08_Entry_Models/Entry_Models.md)
   - [99_Glossary/Glossary.md](knowledge_base/99_Glossary/Glossary.md)

2. **Query-triggered injection**: `kb/selector.py` keyword-matches the user's query + any setup the user named against note frontmatter (`tags`, `aliases`). Injected as additional system-prompt sections.
   - Query mentions "silver bullet" → include [ICT_Silver_Bullet.md](knowledge_base/08_Entry_Models/ICT_Silver_Bullet.md).
   - Query mentions "1h3m" / "Bellissimo" → include [1h3m_by_Bellissimo.md](knowledge_base/09_Setups/1h3m_by_Bellissimo.md).
   - Current time inside 16:30–17:10 Kyiv → inject [NYSE_Open_Setups.md](knowledge_base/09_Setups/NYSE_Open_Setups.md) (later, indices phase).

```python
# copilot/kb/loader.py (sketch)
@dataclass
class Note:
    title: str
    path: Path
    tags: list[str]
    aliases: list[str]
    body: str

def load_all() -> list[Note]:
    notes = []
    for md in Path("knowledge_base").rglob("*.md"):
        if md.name.startswith("_"): continue
        fm, body = split_frontmatter(md.read_text(encoding="utf-8"))
        notes.append(Note(fm["title"], md, fm.get("tags", []), fm.get("aliases", []), body))
    return notes
```

KB remains in its current location (`knowledge_base/`). The co-pilot project reads it read-only — no copy, no edits.

---

## Output format

Claude's final turn emits a **structured markdown report** driven by a prompt template. Human-readable, scan-in-10-seconds, no buried conclusions.

```markdown
# Analysis — BTCUSDT · 2026-04-19 09:00 Kyiv

## Bias
- **HTF (1D):** bullish — D1 FVG @ 66.8k unfilled, last swept SSL @ 65.2k
- **MTF (4H):** bullish, aligned
- **LTF (15m):** pullback into discount — RTO in play

## Active Setup
**1h3m long** — LIVE (killzone 09:00 Kyiv active)

### Confirmed ✅
- 1H fractal swept at 66.45k (wick, closed back inside)
- 15m entered discount zone (fib 0.705)
- Quality liquidity: Asia low raided, not just local fractal

### Pending ⏳
- 3m BOS above 66.52k — not yet confirmed
- Price still inside 1H FVG (50% tagged)

### Invalidates ❌
- 1H close below 66.20k (sweep becomes entrapment)
- 3m makes LL without BOS by 10:00 Kyiv
- News release in window (check calendar manually)

## Levels
| Type | Price | Note |
|---|---|---|
| Entry (on 3m BOS) | ~66.55k | Market after close |
| Stop | 66.15k | Below swept low |
| TP1 | 67.10k | Buyside liquidity @ EQH |
| TP2 | 67.50k | 4H FVG upper |

## RR
1.4R to TP1, 2.4R to TP2. Threshold (≥1.5R) met at TP2 only — partial logic recommended.

## What I checked
- `detect_market_structure` on 1d/4h/1h/15m/3m
- `detect_fvg` on 4h/1h — 3 active
- `detect_liquidity` on 1h/15m — Asia low confirmed swept
- `check_multi_tf_alignment` htf=bullish ltf=pullback → "strong" sync
```

`copilot/llm/prompts.py` contains the exact output-format instructions; the agent is told to emit this block on its final turn. Report text is also persisted to `~/.trading-copilot/reports/{symbol}_{ts}.md`.

---

## Implementation roadmap

### Phase 1 — walking skeleton ✅ DONE

- [x] Project scaffold: `pyproject.toml`, module layout, `.env`, config loader.
- [x] `data/binance.py` (USD-M futures, `fapi.binance.com`) + `data/cache.py` + `data/normalize.py`.
- [x] Detectors: `market_structure`, `bos`, `fvg`, `order_block`, `liquidity`, `fib_zones`, `fractals`, `multi_tf`. **33/33 tests pass.**
- [x] `kb/loader.py` + `kb/selector.py` (keyword-only).
- [x] `llm/tools.py` (auto-discovery), `llm/agent.py` (multi-turn loop + prompt caching), `llm/prompts.py`.
- [x] `cli.py` REPL + session persistence.
- [x] MCP server (`copilot/mcp_server.py`) — all 8 detectors live in Claude Desktop / Cowork. Registered at `%APPDATA%\Claude\claude_desktop_config.json`.

### Phase 2 — Tier B detectors (next)

- [ ] `detect_ifvg` — inverted FVG (polarity flip after full pierce).
- [ ] `detect_breaker_block` — OB fully pierced by a subsequent FVG.
- [ ] `detect_mitigation_block` — impulsive break without sweeping prior extreme.
- [ ] `detect_rejection_block` — 2-candle body-engulf reversal.
- [ ] `detect_sponsored_candle` — OB + confirmed liquidity sweep (composition).
- [ ] `detect_compression` — LRLR narrowing range before expansion.
- [ ] `current_killzone` exposed as MCP tool (session context in Desktop).

**Milestone demo:** LLM autonomously identifies a Silver Bullet or STB/BTS structure end-to-end by chaining ≥4 detector calls; report cites specific detector output for each bullet.

### Phase 3 — Trade Journal ★ HIGH PRIORITY

**Must land before Phases 5–7 have meaningful data. Can start immediately — no new data sources required.**

Every trade and every backtest run is a `TradeRecord`. The schema is designed for filter + aggregation: winrate by setup, by tool, by session, by day of week, by account type.

#### Storage

`~/.trading-copilot/journal/journal.jsonl` — append-only, one JSON object per line. Easy to tail, grep, back up, and parse without migrations.

#### Record schema

```python
# copilot/journal/record.py
@dataclass
class TradeRecord:
    id: str                         # uuid4
    record_type: str                # "trade" | "backtest"
    ts_created: str                 # ISO 8601 UTC (when logged)
    ts_entry: str | None            # ISO 8601 UTC
    ts_exit: str | None             # ISO 8601 UTC
    symbol: str                     # "BTCUSDT"
    account_type: str               # "demo" | "phase1" | "phase2" | "live"
    setup_name: str                 # "1h3m", "silver_bullet", "stb_bts", ...
    tools_confirmed: list[str]      # ["fvg", "order_block", "volume_profile_hvn"]
    tools_pending: list[str]        # checked but not confirmed
    direction: str                  # "long" | "short"
    entry_price: float | None
    sl_price: float | None
    tp_prices: list[float]
    exit_price: float | None
    result: str                     # "win" | "loss" | "be" | "pending" | "missed"
    pnl_r: float | None             # R-multiples (positive = profit)
    rr_planned: float | None        # planned R:R at entry
    session: str                    # "london_open" | "ny_am" | "ny_pm" | "asia" | "ott"
    killzone: str | None            # "09:00" | "15:00" | "17:00" Kyiv
    day_of_week: int                # 0 = Monday
    htf_bias: str                   # "bullish" | "bearish" | "ranging"
    notes: str
    report_path: str | None         # path to saved analysis report
    tags: list[str]                 # free-form for ad-hoc filtering
```

#### File layout

```
copilot/
└── journal/
    ├── __init__.py
    ├── record.py       # TradeRecord dataclass + to_dict / from_dict
    ├── writer.py       # append_record(record) → journal.jsonl
    ├── reader.py       # load_all() → list[TradeRecord]; filter_by(**kwargs)
    └── cli.py          # REPL commands: `log`, `trades`, `edit <id>`
```

#### REPL commands added

- `log` — interactive prompt to fill in a new trade record after a session.
- `trades [--setup <name>] [--symbol <sym>] [--result win|loss] [--last N]` — list trades in table form.
- `edit <id>` — reopen a pending record to fill in exit, result, notes.

Backtest runs use the same schema with `record_type="backtest"`. `tags` includes `["backtest", "run_id:<uuid>"]` for grouping. This makes live vs backtest comparison on the same setup trivial.

---

### Phase 4 — Orderflow detectors ★ HIGH (CD) / MEDIUM (VP) / DEFERRED (Footprint)

Data feasibility per tool on Binance public REST:

| Tool | Data source | Priority |
|---|---|---|
| **Cumulative Delta** | `/fapi/v1/aggTrades` — buy/sell per trade; free, accurate | ★ HIGH |
| **Volume Profile HVN/LVN** | OHLCV bars — distribute volume over [low, high] | MEDIUM |
| **Footprint Imbalances** | Intra-candle bid/ask per price level — not in public REST | DEFERRED |

#### `detect_cumulative_delta(df_ohlcv, df_agg, period="session") -> dict`

New fetch: `copilot/data/binance.py` → `fetch_agg_trades(symbol, start_ms, end_ms)` → `pd.DataFrame[ts, price, qty, is_buyer_maker]`. Candle delta computed by binning trades into bar timestamps.

Primary signals: (1) session net delta direction, (2) divergence (price new high, CD flat/falling), (3) sweep confirmation (sweep without CD support → manipulation confirmed).

```python
{
  "period": "session",
  "session_delta": -12430.5,
  "delta_trend": "negative",          # "positive" | "negative" | "neutral"
  "divergences": [
    {
      "type": "bearish",
      "price_high": 67800.0,
      "cd_at_high": -340.0,
      "bar_ts": "2026-04-25T10:00:00Z",
      "context": "price_new_high_cd_falling"
    }
  ],
  "sweep_confirmation": {
    "last_sweep_ts": "2026-04-25T09:45:00Z",
    "sweep_side": "buyside",
    "cd_at_sweep": -120.0,
    "confirmed_manipulation": true
  },
  "bars": [
    {"ts": "...", "delta": 430.5, "cumulative": -12430.5}
  ]
}
```

`TOOL_SCHEMA` description: "Use to confirm or dispute a liquidity sweep — if CD did not rise with a BSL sweep, the sweep is likely manipulation, not genuine demand."

#### `detect_volume_profile(df, resolution_pct=0.1, session_bars=None) -> dict`

Approximation: distribute each OHLCV bar's volume uniformly across `N = (high − low) / tick` price buckets. Aggregate over the period. Identify HVN (top 15% volume density) and LVN (bottom 15%). Tick size per symbol from `config.toml`.

```python
{
  "poc": 67150.0,
  "vah": 67480.0,
  "val": 66820.0,
  "hvn_nodes": [
    {"price_mid": 67150.0, "price_low": 67100.0, "price_high": 67200.0,
     "volume_pct": 18.4}
  ],
  "lvn_nodes": [
    {"price_mid": 66980.0, "price_low": 66950.0, "price_high": 67010.0,
     "volume_pct": 0.8}
  ],
  "current_price_location": "above_poc",
  "nearest_hvn_above": {"price_mid": 67480.0, "distance_atr": 1.2},
  "nearest_hvn_below": {"price_mid": 67150.0, "distance_atr": 0.3},
  "nearest_lvn_on_path": {"price_mid": 66980.0, "distance_atr": 0.8, "side": "below"}
}
```

KB integration: when `volume_profile_hvn` or `volume_profile_lvn` appears in `tools_confirmed`, `kb/selector.py` injects [`04_Market_Profile/Volume_Profile.md`](knowledge_base/04_Market_Profile/Volume_Profile.md) into the system prompt.

#### `detect_footprint_imbalances` — Tier C (deferred)

Requires intra-candle bid/ask volume per price level. Binance public REST does not expose this. Deferred until a L2/tick data source is wired in. The KB note is still injectable via selector when user mentions "footprint" — the LLM reasons about the concept without a live detector.

---

### Phase 5 — Backtest engine ✅ DONE

Run the detector library over historical OHLC data with simulated setup conditions. Results written to journal as `record_type="backtest"` entries, enabling live vs backtest comparison by the same metrics.

#### Design

```
copilot/
└── backtest/
    ├── __init__.py
    ├── engine.py       # BacktestEngine.run(symbol, tf, start, end, setup_rules)
    ├── rules.py        # SetupRule: declarative detector confluence requirements
    ├── simulate.py     # simulated_exit(entry, sl, tp, future_bars) → result, pnl_r
    └── report.py       # summary per run; writes to journal
```

#### Look-ahead prevention

Engine passes `df.iloc[:i+1]` to every detector call at bar index `i`. Entry triggered by close of bar `i+1`. Exit simulated on subsequent bars (first bar that touches TP or SL wick).

#### SetupRule (current schema)

```python
@dataclass
class SetupRule:
    name: str
    direction: str                        # "long" | "short"
    conditions: list[Condition]           # entry TF detector conditions
    entry_after: str                      # "next_open" | "signal_close" | "fvg_ce" | ...
    sl_logic: str                         # "atr:N" | "ob_lower" | ...
    tp_logic: str                         # "rr:N" | "liquidity_above" | ...
    # Multi-TF
    htf_conditions: list[HTFCondition]    # evaluated on separate pre-fetched HTF DataFrames
    # LTF entry confirmation (3-tier flow)
    entry_tf: str | None                  # e.g. "5m" — if set, enters _LTF_SCAN after signal
    entry_conditions: list[Condition]     # conditions on LTF bars
    entry_after_ltf: str                  # "signal_close" | "next_open"
    max_entry_wait_bars_ltf: int          # abort LTF scan after N bars
    # Partial TP management
    tp_levels: list[TPLevel]              # e.g. [TPLevel("rr:1.8", 0.5), TPLevel("rr:4.0", 0.5)]
    sl_after_tp1: str | None              # "be" | None
    # Trade management
    max_bars_open: int | None             # time-based exit; result="expired"
    fee_bps: float                        # e.g. 8.0 = 0.08% per side; deducted as R fraction
    risk_pct: float                       # account risk % for equity curve calculation
```

One `TradeRecord` per triggered entry; `tags` includes `["backtest", "run_id:<uuid>"]`.

#### Engine state machine

`_IDLE` → `_SIGNAL` → [`_LTF_SCAN`] → `_IN_TRADE` → [`_IN_TRADE_P2`] → exit

- HTF conditions evaluated via `_evaluate_htf_conditions()` using per-HTF-bar cache
- LTF scan cursor seeded by `_find_ltf_idx()` — no look-ahead across TF boundaries
- `_IN_TRADE_P2` checked before `_IN_TRADE` in the per-bar loop so partial-TP management happens before new entry logic

---

### Phase 6 — Statistics aggregation ✅ DONE

```
copilot/
└── stats/
    ├── __init__.py
    ├── aggregator.py   # compute_stats(records, group_by=[...]) → StatsResult
    └── cli.py          # REPL command: `stats [--group setup|tool|session|dow]`
```

#### Metrics

| Metric | Formula |
|---|---|
| Winrate | wins / (wins + losses) |
| Avg RR | mean(pnl_r) for completed trades |
| Profit Factor | sum(pnl_r > 0) / abs(sum(pnl_r < 0)) |
| Expectancy | winrate × avg_win_r − lossrate × avg_loss_r |

Group-by dimensions: `setup_name`, individual tool in `tools_confirmed`, `session`, `day_of_week`, `account_type`, `htf_bias`, `record_type` (live vs backtest).

**Tool-effectiveness ranking** (`stats --group tool`): lists each tool with conditional winrate (trades where tool was confirmed vs not confirmed). Tools with Δwinrate < 0 flagged as potentially redundant — directly answers the KB question "which tools actually improve outcome?"

REPL examples:
```
> stats --group setup
> stats --group tool --setup 1h3m
> stats --compare live backtest --setup silver_bullet
```

---

### Phase 7 — Dashboard ★ LOW-MEDIUM (terminal-first, no web UI) ← NEXT

```
copilot/
└── dashboard/
    ├── __init__.py
    └── tui.py          # `python -m copilot dashboard` → rich TUI
```

| Panel | Content |
|---|---|
| Today | Today's trades, session P&L in R, active killzone countdown |
| Equity curve | ASCII sparkline of cumulative R, last 30/90 days |
| Winrate trend | Rolling 20-trade winrate, 50% benchmark line |
| Heatmap | Winrate by day of week × session (colour-coded) |
| Top setups | Sorted by profit factor (live / backtest / combined) |
| Tool leaderboard | Tools ranked by Δwinrate contribution |
| Worst conditions | Setup + session + DOW combos with PF < 1 |

Implemented with `rich.table`, `rich.panel`. Launched via `python -m copilot dashboard` or `> dashboard` inside the REPL.

---

### Phase 8 — Quality-of-life (ongoing)

**Composite MCP detectors ✅ DONE:**
- [x] `check_absorption_at_poi` — identifies absorption bars (high vol, tiny range, close near high) at unmitigated OBs or active FVGs; `poi_type` = ob/fvg/ob+fvg; registered in `_DELTA_TOOLS`.
- [x] `check_cd_divergence_at_structure` — CD divergence at key structural swing levels; sweep confirmation required; `signal_strength` graded weak/moderate/strong; registered in `_DELTA_TOOLS`.

**Remaining:**
- [ ] Scheduled reports at killzone times (09:00 / 15:00 / 17:00 Kyiv).
- [ ] Embeddings-based KB retrieval if keyword matching proves brittle.
- [ ] Report archive browser in REPL (`history`, `read`).

---

### Phase 9 — More instruments (after crypto workflow is solid)

**Scope: forex, metals, indices — all deferred until Phases 3–7 are stable on crypto.**

Add data sources in order of ease: **XAU/USD → EUR/USD → GER40 + EU50 → NAS100 + SP500**.
- Each family = one new `data/*.py` implementing `DataSource`. Detectors unchanged.
- Session/killzone tables extended per instrument class (FX, indices, metals).

---

### Priority summary

#### Completed phases

| Phase | Feature | Status |
|---|---|---|
| 1 | Walking skeleton (data, Tier A detectors, KB, LLM, REPL, MCP) | ✅ DONE |
| 2 | Tier B detectors + Pine Script generator | ✅ DONE |
| 3 | Trade Journal (SQLite WAL) | ✅ DONE |
| 4a | Cumulative Delta detector | ✅ DONE |
| 4b | Volume Profile HVN/LVN detector | ✅ DONE |
| 4c | Footprint Imbalances | DEFERRED — L2 data unavailable |
| 5 | Backtest engine (+ walk-forward, HTF conditions, partial TP, fee model) | ✅ DONE |
| 6 | Statistics aggregation | ✅ DONE |
| 8a | Composite MCP detectors (absorption_at_poi, cd_divergence_at_structure) | ✅ DONE |

> ⚠️ "DONE" above means *built*, not *validated*. The June 2026 audit invalidated all Phase 5 backtest results (look-ahead leaks) and found Phases 4/8a detectors broken (see Course Correction #2). Phase 8a composites are quarantined per P0-4.

#### Active roadmap — June 2026 (authoritative; supersedes the post-May table)

Sequencing rule: each later phase consumes data produced by the earlier ones; right now that data is contaminated at the source. **No feature work (P3+) until P0–P1 land.** Until P0-1/P0-2 land, treat all current reports and backtests as unvalidated.

| Priority | Item | Fixes | Effort | Status |
|---|---|---|---|---|
| **P0-1 — BLOCKER** | Drop forming bar in `normalize_binance` (`include_forming=False`) | Every live signal repaints | XS | ✅ DONE 2026-06-10 |
| **P0-2 — BLOCKER** | Fix backtest look-ahead: LTF scan from signal-bar *close*; HTF slice by HTF bar *close*; HTF cache key += kwargs; HTF fetch respects start/end. Add automated look-ahead regression test | All backtest numbers invalid | S | ✅ DONE 2026-06-10 — regression suite at `tests/test_lookahead_regression.py` |
| **P0-3** | Add `smartmoneyconcepts` dependency; rewrap swings / BOS-CHoCH / OB / FVG / liquidity as thin JSON wrappers | R1, R2, R3; replaces broken market_structure, bos, order_block, liquidity internals | M | ✅ DONE 2026-06-10 — `smc_lib.py` adapter; market_structure/bos wrap `smc.bos_choch`. Deviation: `smc.ob` empirically inherits R1 (probes/probe_smc_lib.py), so order_block keeps the swing-break scan over RAW confirmed swings; liquidity wraps `smc.liquidity` + side-typed close-back sweeps. Regression suite: tests/test_detectors_smc_rewrap.py |
| **P0-4** | Quarantine broken tools from MCP list + prompt until rewritten: `detect_compression`, `check_cd_absorption`, `check_absorption_at_poi`, `check_cd_divergence_at_structure`; strip `sweep_confirmation`/`divergences` from CD output (keep `session_delta`/`delta_trend`) | Prompt currently upgrades confidence on noise | XS | ✅ DONE 2026-06-10 — `_QUARANTINED_TOOLS` in `llm/tools.py`; CD output stripped; prompt rules rewritten. Note: `rules_orderflow.py` rules referencing removed CD fields now never trigger (intended) |
| **P0-5** | Rewrite CD divergence swing-to-swing (pivot CD vs pivot CD); sweep anchoring to liquidity pools with side semantics | R4, R5 | M | ✅ DONE 2026-06-10 — divergence = confirmed price extreme vs prior CD peak/trough; sweep_confirmation reuses detect_liquidity pools (close-back, side-typed). Prompt updated: CD = secondary confluence only |
| **P0-6** | Honest cost model: two-sided fees, slippage param, funding approximation; fix `tools_confirmed` (record actual confirmed conditions); fix `_resolve_limit_level` direction check; route delta fetch through cache/DataSource | Backtest expectancy overstated; tool ranking degenerate | S | ✅ DONE 2026-06-10 (except funding approximation — needs funding-rate fetch, deferred to P0-7 prep). `fee_bps` now per-side on entry+exit notional; `slippage_bps` added to SetupRule |
| **P0-7** | Re-baseline: rerun all rules walk-forward with P0-1…P0-6 in place. This is the first trustworthy expectancy number | Evidence loop | S | pending |
| **P1-1** | Convert `probes/*.py` into pytest regression suite; delete vacuous schema tests (liquidity, CD, compression test files) | Test suite false confidence | S | pending |
| **P1-2** | Analysis workflow revision (`prompts.py` + `state.py`): HTF-POI hard gate, `## HTF POI` section, conflict hierarchy (MS > sweep > OB/FVG > orderflow), position management; remove noise-signal upgrade instructions | Protocol/prompt drift | S | pending |
| **P1-3** | Fix `agent.py`: key tool results by `(name, symbol, tf)`; remove duplicate assistant append. Add automated report-vs-trace check (every price in report must appear in a tool result; fail loudly) | State diff corrupt; anti-hallucination promise unenforced | S | pending |
| **P1-4** | Trade probability assessment (confidence weights) | — | S | pending — only meaningful after P0 |
| **P2-1** | Small detector fixes: `fib_zones` direction param (short OTE); `current_killzone` weekday gate; `multi_tf` single coherent code path; `fractals.is_swept` → close-back semantics or rename `is_taken`; `rejection_block` doc/logic alignment; unify ATR definition (true range, rolling per-bar) | June ⚠️ tier | S | pending |
| **P2-2** | Rebuild breaker/mitigation/sponsored on the library OB (single OB universe); sponsored candle per audit: sweep candle = OB, sweep of a *pool* | R3, R4 | M | pending |
| **P2-3** | QuantStats tearsheet (promote — do instead of growing `stats/`); binomial CI on winrates in `stats` output | Honest reporting | S | pending |
| **P2-4** | Journal pattern analysis (LLM error detection) | — | M | pending |
| **P3** | Dashboard TUI (rich terminal) | — | M | blocked by P0–P1 |
| **P3** | Multi-LLM provider abstraction | — | — | LOW — deferred |
| **P4** | Screenshot / text trade analysis (multimodal) | — | M | blocked by P1-2 |
| **P5** | More instruments (XAU, FX, indices) | — | L | blocked by stable crypto workflow |
| **P5** | QoL (scheduled reports, embeddings KB, archive browser) | — | — | deferred |

Optional (evaluate during P0-2): replace hand-rolled fill/fee/metrics simulation in `engine.py` with vectorbt, keeping `SetupRule` + detectors as the signal layer. Minimum bar if not migrating: P0-2 + P0-6 + the look-ahead regression test.

---

### P1 — Analysis workflow revision

**Scope: `llm/prompts.py` + `llm/state.py`**

Current state: prompts describe *what* to do but don't enforce order or handle conflicting signals. `state.py` field names will change with detector rewrites.

Changes needed:

1. **HTF POI rule (hard-enforced):** Do not proceed to LTF analysis until HTF POI is identified. Add explicit gate in prompt: "If no HTF POI found → output 'No setup — HTF POI not established' and stop."
2. **Conflict resolution hierarchy:** Explicit priority order when signals disagree: Market Structure > Liquidity sweep > OB/FVG > Orderflow. State what to do when D1 bullish but H4 bearish (HTF always wins unless H4 shows confirmed cBOS).
3. **Position management rules in prompt:** Rules from KB (re-sweep, RTGS, adding to winners) currently not reflected in output format. Add `## Position Management` section to output template.
4. **Output format update:** Add `## HTF POI` section before `## Levels`. Expand Confidence field to reflect probability assessment (see P1b below).
5. **`state.py` sync:** Update field names to match rewritten detectors. Add version field to state JSON for forward compatibility.

### P1b — Trade probability assessment

**Scope: integrated into existing analysis sections, not a new section**

After P0 detectors are correct, LLM evaluates cumulative confidence based on:

| Factor | Bullish weight | Bearish weight |
|---|---|---|
| TF sync (D1+H4+H1 aligned) | +++ | +++ |
| Liquidity sweep confirmed before POI | ++ | ++ |
| POI quality (SC > OB > FVG > IFVG) | + per tier | + per tier |
| BOS/cBOS on entry TF | ++ | ++ |
| In OTT window + killzone | + | + |
| Distance to FTA/PTA (nearer = better) | + | + |
| Direction (reversal vs continuation) | base rate −10% | base rate −10% |
| CD / orderflow confirmation | + | + |

**Output format:** Confidence integrated into existing sections as `HIGH / MEDIUM / LOW` with explicit listed reasons. Not a percentage number. Example:

```
## Active Setup
**1h3m long** — LIVE
**Confidence: HIGH** — D1+H4+H1 aligned bullish, SSL swept, SC-quality POI, in OTT window
**Confidence: LOW** — H4 desync, no sweep, outside OTT
```

### P2 — Pine Script visual design system

**Scope: `detectors/pine_script.py` + new `detectors/pine_design.py`**

Current state: all zones drawn as plain boxes with small labels. No visual hierarchy.

Process:
1. Define design system in `pine_design.py`: color palette per zone type, label sizes, line styles per state (active/mitigated/tested)
2. Present as HTML preview for approval before implementation
3. Apply to `pine_script.py` after approval

Design system rules:
- SC/Sponsored candle: highest visual weight (thick border, bright color)
- OB: medium weight
- FVG: light fill, dashed border
- Mitigated zones: 50% opacity, grey tint
- Liquidity levels: horizontal dashed lines with label
- Dark chart theme as default

**Do last — after all detectors produce correct output.**

### P2b — QuantStats tearsheet

**Scope: new REPL command `journal tearsheet`**

Integrates `ranaroussi/quantstats` library. Generates HTML tearsheet from journal records:
- Equity curve, drawdown chart, rolling Sharpe
- Monthly returns heatmap
- Benchmark: BTC/ETH buy-and-hold comparison
- Saved to `~/.trading-copilot/reports/tearsheet_{ts}.html`, opened in browser

Complements (not replaces) the custom `stats/aggregator.py` — QuantStats handles trading metrics, aggregator handles tool-effectiveness and KB-specific groupings.

### P2c — Journal pattern analysis

**Scope: new REPL command `journal analyze`**

Sends full journal to LLM with analytical system prompt. Tasks:
- Find conditions where trades systematically lose (time, session, setup, TF desync)
- Detect execution errors (premature entry, wrong SL placement) via `tools_confirmed` vs result correlation
- Correlate "number of conditions confirmed" with winrate
- Propose specific rule adjustments with evidence: not "avoid Monday shorts" but "4 of 6 Monday short losses occurred when H4 showed cBOS on the open — add H4 cBOS filter to short rules"

Output: structured Markdown report saved to `~/.trading-copilot/reports/journal_analysis_{ts}.md`

### P4 — Screenshot / text trade analysis

**Scope: new mode in CLI and/or MCP tool**

Extends the system to analyze external trades:

- **Screenshot:** pass chart image to multimodal LLM → extract structure, POI, entry, SL/TP → evaluate against KB rules
- **Text description:** parse trade description ("entered BTC long on H1 OB after SSL sweep") → analyze against rules + find errors
- **Use cases:** reviewing others' trades, retrospective own-trade analysis, learning from examples
- **Journal integration:** save analyzed trade as `record_type="reviewed"` with `tags=["external"]`

---

### Explicitly deferred

- Trade execution, broker APIs, order placement.
- Footprint Imbalances (intra-candle L2 tick data unavailable via public REST).
- VWAP / TPO detectors (tick data required; TPO approximation deferred).
- Web/GUI frontend (REPL + TUI dashboard matches the user's discretionary workflow).

---

## Verification

### Per detector (automated)

- `pytest tests/test_detectors_*.py` — fixture-based. Each detector has:
  - A positive case: known-good OHLC fixture where the object exists; assert fields.
  - A negative case: fixture where the object shouldn't be found; assert empty/none.
  - An edge case: insufficient bars, flat market, or boundary condition.
- Fixtures are **parquet files** committed to the repo, generated once from Binance historical data for known setups, then frozen.

### Agent loop (automated)

- `tests/test_agent_loop.py` mocks the Anthropic client with scripted `tool_use` responses and verifies the dispatcher calls the right detector with the right args and returns results in the right message shape. No real API calls in CI.

### End-to-end (manual, per phase milestone)

Run the REPL against real Binance data during a live killzone (e.g., 09:00 Kyiv Mon–Fri) and check:
1. The report structure matches the template (Bias / Setup / Confirmed / Pending / Invalidates / Levels / RR).
2. Every "Confirmed ✅" or "Pending ⏳" bullet corresponds to an actual tool call visible in the transcript log.
3. No hallucinated price levels — every number in the report appears in at least one tool result.
4. The LLM respects global rules: no BE mentioned, no entries placed intra-candle, killzone discipline.

If check (3) fails even once, treat it as a P0 bug — this is the failure mode the whole architecture is designed to prevent.

### Cost guardrail

Log `input_tokens`, `output_tokens`, `cache_read_tokens` per turn to `~/.trading-copilot/usage.jsonl`. After 1 week of real use, review and decide whether KB injection strategy needs tightening.

---

## Files the developer touches first (Phase 1, in order)

1. `pyproject.toml` — dependencies: `anthropic`, `pandas`, `pyarrow`, `httpx`, `python-dotenv`, `tomli`, `pytest`.
2. [copilot/data/normalize.py](trading-copilot/copilot/data/normalize.py) — schema contract.
3. [copilot/data/binance.py](trading-copilot/copilot/data/binance.py) — fetch klines, return normalized DF.
4. [tests/fixtures/](trading-copilot/tests/fixtures/) — record ~6 parquet fixtures covering the Tier A cases.
5. [copilot/detectors/fvg.py](trading-copilot/copilot/detectors/fvg.py) — simplest detector, establishes the pattern.
6. `tests/test_detectors_fvg.py` — proves the pattern works end-to-end.
7. Remaining Tier A detectors, in order: `fractals` → `market_structure` → `bos` → `liquidity` → `order_block`.
8. [copilot/kb/loader.py](trading-copilot/copilot/kb/loader.py) — read KB into memory, parse frontmatter.
9. [copilot/llm/tools.py](trading-copilot/copilot/llm/tools.py) — auto-discovery.
10. [copilot/llm/agent.py](trading-copilot/copilot/llm/agent.py) — loop + caching.
11. [copilot/cli.py](trading-copilot/copilot/cli.py) — REPL.
