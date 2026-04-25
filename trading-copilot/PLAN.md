# Trading Co-Pilot — Implementation Plan

## Context

The user is a discretionary SMC/ICT trader with a complete, structured Obsidian KB at [knowledge_base/](knowledge_base/). Goal: build a Python system where **Claude (via Anthropic SDK) reads the KB as narrative context, then calls algorithmic detectors over OHLC data as tools** to produce a structured market analysis that the trader acts on manually.

**Why this shape.** The KB already encodes the "what to think" (concepts, setups, entry models, global rules). What the LLM cannot do alone is reliably measure things on a chart — fractal sweeps, FVG fill depth, OB mitigation state, multi-TF confluence. Detectors close that gap by returning **compact, self-describing JSON** the LLM can reason over without hallucinating candle positions.

**Decisions locked from the kickoff:**
- LLM backend: Anthropic SDK only (Sonnet 4.6 default, Opus 4.7 for heavy multi-TF reasoning). Native tool-use loop.
- Instruments v1: **crypto only (BTC, ETH)** via Binance public REST. Data layer kept pluggable so XAU/USD, EUR/USD, GER40/EU50, NAS100/SP500 can be added later.
- Interface: **interactive REPL/chat** in the terminal. Multi-turn conversation, session persistence.

**Hard constraints** (from [_Global_Rules.md](knowledge_base/00_Index/_Global_Rules.md)):
- No order placement. Analysis only.
- Detectors pure-functional, unit-testable against fixture OHLC (no live API dependency in tests).
- Multi-TF is non-negotiable: D1 → H4 → H1 → M15 → M3/M1 is how the user thinks, and the system must mirror it.
- Session-awareness: OTT window 09:00–17:00 Kyiv, killzones at 09:00 / 15:00 / 17:00 Kyiv; NY AM/PM windows for indices (later).

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
```python
{
  "state": "bullish" | "bearish" | "ranging",
  "last_swing_high": {"price": 67234.5, "ts": "2026-04-18T14:00:00Z", "strength": "strong"},
  "last_swing_low":  {"price": 66112.0, "ts": "2026-04-18T09:00:00Z", "strength": "weak"},
  "bars_in_state": 42
}
```
Strength: "strong" if the swing was followed by a BOS; "weak" otherwise.

#### `detect_bos(df, swing_lookback=5) -> dict`
Looks for the **most recent** break of a prior swing by candle close.
```python
{
  "type": "BOS" | "MSS" | "cBOS" | "none",
  "direction": "bullish" | "bearish",
  "broken_level": 67234.5,
  "break_ts": "2026-04-18T15:00:00Z",
  "displacement": {"candles": 3, "atr_multiple": 2.4}  # strength proxy
}
```
- `BOS` = break in trend direction (continuation).
- `MSS` = break against trend (structure shift; user's term).
- `cBOS` = new HH/LL without structural break.

#### `detect_fvg(df, min_width_atr=0.15, max_age_bars=200) -> dict`
3-candle imbalance scan. Returns **active** (unfilled or partially filled) FVGs only.
```python
{
  "fvgs": [
    {
      "type": "bullish",
      "upper": 67100.0, "lower": 66950.0,
      "formed_ts": "2026-04-18T12:00:00Z",
      "fill_percentage": 0,
      "fill_state": "untouched" | "IOFED" | "CE_tagged" | "filled",
      "age_bars": 5
    },
    …
  ],
  "count_active": 3
}
```
IOFED = touched ≥1% depth. CE_tagged = 50% depth. Filled → dropped from list unless inverted (see IFVG).

#### `detect_order_block(df, ms_state, lookback=60) -> dict`
Last opposing candle before an impulse that broke structure. Requires `ms_state` (result of structure detector) to filter quality.
```python
{
  "obs": [
    {
      "type": "bullish",
      "high": 66980.0, "low": 66890.0,
      "formed_ts": "2026-04-18T11:00:00Z",
      "has_fvg_after": true,       # quality marker per KB
      "is_mitigated": false,
      "distance_atr": 0.8          # how close current price is
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

### Phase 5 — Backtest engine ★ MEDIUM (after Phase 3 schema is frozen)

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

#### SetupRule

```python
@dataclass
class SetupRule:
    name: str                        # "1h3m_long"
    direction: str                   # "long" | "short"
    conditions: list[Condition]      # detector name + field + assertion
    entry_after: str                 # "bos_close" | "fvg_retrace_ce"
    sl_logic: str                    # "below_swept_low" | "ob_lower"
    tp_logic: str                    # "liquidity_above" | "next_hvn"
    required_session: list[str] | None
    required_killzone: list[str] | None
```

One `TradeRecord` per triggered entry; `tags` includes `["backtest", "run_id:<uuid>"]`.

---

### Phase 6 — Statistics aggregation ★ MEDIUM (meaningful after ≥30 journal records)

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

### Phase 7 — Dashboard ★ LOW-MEDIUM (terminal-first, no web UI)

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

| Phase | Feature | Priority | Prerequisite |
|---|---|---|---|
| 3 | Trade Journal | **HIGH** | — |
| 4a | Cumulative Delta detector | **HIGH** | — |
| 4b | Volume Profile HVN/LVN detector | MEDIUM | — |
| 4c | Footprint Imbalances | DEFERRED | L2 data source |
| 5 | Backtest engine | MEDIUM | Phase 3 schema |
| 6 | Statistics aggregation | MEDIUM | Phase 3 ≥30 records |
| 7 | Dashboard TUI | LOW-MEDIUM | Phase 6 |
| 8 | QoL (scheduled reports, embeddings) | LOW | — |
| 9 | More instruments (XAU, FX, indices) | LOW | Phases 3–7 stable |

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
