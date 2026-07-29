"""Empirical probes: construct known-truth fixtures, check detector verdicts."""
import os, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd

def mkdf(rows, freq="1h"):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, index=idx)
    df.index.name = "ts"
    if "volume" not in df.columns:
        df["volume"] = 100.0
    return df[["open", "high", "low", "close", "volume"]]

def bar(o, h, l, c, v=100.0):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}

P = lambda name, ok, detail: print(f"[{'PASS' if ok else 'FAIL'}] {name}\n       {detail}")

# ============================================================
# PROBE 1: market_structure — clean uptrend (HH/HL) in a pullback
# Expectation (SMC): structure stays bullish during a normal retracement.
# ============================================================
from copilot.detectors.market_structure import detect_market_structure
rows = []
price = 100.0
# Build 4 clear up-legs with pullbacks, lookback=2 swings confirmed
for leg in range(4):
    base = 100 + leg * 10
    for j in range(5):   # impulse up
        rows.append(bar(base + j*2, base + j*2 + 2.2, base + j*2 - 0.4, base + j*2 + 2))
    for j in range(3):   # shallow pullback (higher low preserved)
        top = base + 10
        rows.append(bar(top - j*1.5, top - j*1.5 + 0.5, top - j*1.5 - 1.7, top - j*1.5 - 1.5))
# final shallow pullback in progress (3 red bars, well above last higher-low)
last_top = 140
for j in range(3):
    rows.append(bar(last_top - j*1.2, last_top - j*1.2 + 0.3, last_top - j*1.2 - 1.4, last_top - j*1.2 - 1.2))
df = mkdf(rows)
ms = detect_market_structure(df, swing_lookback=2)
P("market_structure: uptrend stays bullish during pullback",
  ms["state"] == "bullish",
  f"state={ms['state']} last_bos_type={ms['last_bos_type']} (HH/HL intact, price retracing)")

# Same df, advance one more red bar — does state flip bar-to-bar?
df2 = mkdf(rows + [bar(136.4, 136.6, 134.8, 135.0)])
ms2 = detect_market_structure(df2, swing_lookback=2)
print(f"       next bar: state={ms2['state']} (flip = unstable bias)")

# ============================================================
# PROBE 2: cumulative_delta — genuine breakout labeled as "sweep"?
# Last bar: strong close ABOVE prior highs, tiny upper wick (0.4% of range),
# positive delta. A breakout, not a sweep. Expect: no sweep_confirmation.
# ============================================================
from copilot.detectors.cumulative_delta import detect_cumulative_delta
rows = [bar(100+i*0.1, 100.5+i*0.1, 99.5+i*0.1, 100.2+i*0.1) for i in range(30)]
rows.append(bar(103.2, 106.02, 103.0, 106.0))  # breakout: closes at top, wick 0.02/3.02=0.7%
df = mkdf(rows)
df["buy_vol"] = 80.0; df["sell_vol"] = 20.0; df["delta"] = 60.0  # buyers dominant
r = detect_cumulative_delta(df)
sw = r.get("sweep_confirmation")
P("cumulative_delta: breakout bar NOT labeled a sweep",
  sw is None,
  f"sweep_confirmation={sw}")

# ============================================================
# PROBE 3: cumulative_delta divergence — only fires if LAST bar is the extreme?
# Classic divergence: high at bar -5 (CD high), retest high at bar -3 with lower CD,
# now 2 bars later. Real swing-to-swing divergence exists but last bar is not the extreme.
# ============================================================
rows = [bar(100, 101, 99, 100.5) for _ in range(20)]
rows.append(bar(100.5, 105, 100.4, 104.5))   # push high, strong delta
rows.append(bar(104.5, 105.2, 103.0, 103.5)) # top 1
rows.append(bar(103.5, 105.3, 103.2, 103.6)) # top 2 (higher high, weaker delta)
rows.append(bar(103.6, 103.8, 102.5, 102.8))
rows.append(bar(102.8, 103.0, 102.0, 102.2)) # last bar — not the extreme
df = mkdf(rows)
deltas = [10]*20 + [500, 50, -200, -50, -30]
df["delta"] = deltas; df["buy_vol"] = 0; df["sell_vol"] = 0
r = detect_cumulative_delta(df)
P("cumulative_delta: swing-to-swing bearish divergence detected",
  any(d["type"] == "bearish" for d in r["divergences"]),
  f"divergences={r['divergences']} (price made HH at bar -3 with falling CD)")

# ============================================================
# PROBE 4: check_cd_absorption — below-average volume passes as 'high volume'?
# Last bar: volume 0.75x average, small range, close near high.
# Real absorption requires clearly elevated volume. Expect: not detected.
# ============================================================
from copilot.detectors.orderflow_composite import check_cd_absorption
rows = [bar(100+i*0.05, 101+i*0.05, 99+i*0.05, 100.5+i*0.05, v=100) for i in range(29)]
rows.append(bar(101.4, 101.55, 101.35, 101.52, v=75))  # small quiet bar, BELOW avg volume
df = mkdf(rows)
r = check_cd_absorption(df)
P("check_cd_absorption: quiet below-avg-volume bar NOT absorption",
  not r["absorption_detected"],
  f"absorption_detected={r['absorption_detected']} vol_ratio={r['vol_ratio']} (volume is 25% BELOW average)")

# ============================================================
# PROBE 5: fib_zones — OTE for a SHORT setup
# Bearish swing: high 110 -> low 100. Short OTE = retracement UP to 106.2-107.9.
# Price now 107 (inside short OTE). Tool has no direction param.
# ============================================================
from copilot.detectors.fib_zones import detect_fib_zones
rows = [bar(110 - i*0.5, 110.2 - i*0.5, 109.5 - i*0.5, 109.8 - i*0.5) for i in range(20)]
rows.append(bar(106.8, 107.2, 106.5, 107.0))  # retraced up to 107 = 0.7 retr. of 110->100
df = mkdf(rows)
r = detect_fib_zones(df, swing_high=110, swing_low=100)
P("fib_zones: price 107 inside SHORT OTE (bearish 110->100 swing) flagged in_ote",
  r["in_ote"],
  f"in_ote={r['in_ote']} ote_band={r['ote']} location={r['current_price_location']} (band is the LONG-side OTE only)")

# ============================================================
# PROBE 6: compression on pure random noise — false-positive rate
# ============================================================
from copilot.detectors.compression import detect_compression
rng = np.random.default_rng(7)
hits = active = 0
for trial in range(50):
    closes = 100 + np.cumsum(rng.normal(0, 0.5, 80))
    rows = []
    for c in closes:
        spread = abs(rng.normal(0, 0.6)) + 0.1
        rows.append(bar(c, c + spread, c - spread, c + rng.normal(0, 0.2)))
    r = detect_compression(mkdf(rows))
    hits += r["count"] > 0
    active += r["active"]
P("compression: low false-positive rate on pure noise (<20% of charts)",
  hits / 50 < 0.2,
  f"compressions found on {hits}/50 random charts; 'active right now' on {active}/50")

# ============================================================
# PROBE 7: liquidity — candle that CLOSES through the high (break, not sweep)
# Expect: not reported in recent_sweeps (break != sweep)... and pool removed.
# ============================================================
from copilot.detectors.liquidity import detect_liquidity
rows = [bar(100, 101, 99, 100.5) for _ in range(10)]
rows += [bar(100.5, 104, 100.4, 103.5)]              # swing high 104
rows += [bar(103.5, 103.8, 101.0, 101.5) for _ in range(5)]
rows += [bar(101.5, 106, 101.4, 105.8)]              # CLOSES well above 104 = break
rows += [bar(105.8, 106.2, 105.0, 105.5) for _ in range(3)]
df = mkdf(rows)
r = detect_liquidity(df, lookback=30)
break_as_sweep = any(s["side"] == "buyside" and abs(s["swept_level"] - 104) < 0.5 for s in r["recent_sweeps"])
P("liquidity: close-through break NOT misreported as wick sweep",
  not break_as_sweep,
  f"recent_sweeps={r['recent_sweeps'][:2]}")

# True wick sweep: wick above 104, close back below.
# rows[:16] = everything BEFORE the close-through break bar — a pool that
# was already broken by close cannot be swept afterwards.
rows2 = rows[:16]
rows2 += [bar(101.5, 104.6, 101.3, 101.8)]           # wick sweep of 104, closes back
rows2 += [bar(101.8, 102.2, 101.2, 101.6) for _ in range(3)]
df = mkdf(rows2)
r = detect_liquidity(df, lookback=30)
got_sweep = any(s["side"] == "buyside" and abs(s["swept_level"] - 104) < 0.5 for s in r["recent_sweeps"])
P("liquidity: genuine wick sweep IS reported", got_sweep, f"recent_sweeps={r['recent_sweeps'][:2]}")

# ============================================================
# PROBE 8: sponsored_candle — sweep of a LIQUIDITY level vs OB's own low
# Setup per KB: prior swing low at 95 swept by wick, then bearish OB candle, then impulse.
# But detector checks sweep vs OB's own low, not the liquidity level.
# Construct: sweep takes prior swing low 95 (close back above), OB candle low is 98
# (never wicked below 98 before) -> detector should find it per KB; does it?
# ============================================================
from copilot.detectors.sponsored_candle import detect_sponsored_candle
rows = [bar(100, 101, 99, 100.2) for _ in range(12)]
rows += [bar(100, 100.5, 95.0, 96.0)]      # decline to the lows
rows += [bar(96.0, 96.5, 94.6, 95.8)]      # WICK SWEEP of 95 area, closes back
rows += [bar(95.8, 99.0, 95.7, 98.8)]      # recovery
rows += [bar(98.8, 99.2, 98.0, 98.1)]      # bearish OB candle (low 98)
rows += [bar(98.1, 103.5, 98.05, 103.2)]   # bullish impulse closes above OB high
rows += [bar(103.2, 103.6, 102.5, 103.0) for _ in range(3)]
df = mkdf(rows)
r = detect_sponsored_candle(df, lookback=30, sweep_window=5)
P("sponsored_candle: KB-pattern (sweep of prior low -> OB -> impulse) detected",
  r["count"] > 0,
  f"count={r['count']} candles={r['candles']}")

# ============================================================
# PROBE 9: multi_tf — LTF ranging inside HTF trend: coherent output?
# ============================================================
from copilot.detectors.multi_tf import check_multi_tf_alignment
r = check_multi_tf_alignment("bullish", "ranging", "4h", "15m")
P("multi_tf: LTF ranging -> role/aligned/quality fields coherent",
  not (r["ltf_role"] == "unclear" and r["sync_quality"] == "weak"),
  f"aligned={r['aligned']} ltf_role={r['ltf_role']} sync_quality={r['sync_quality']} (mixed verdicts from two disjoint code paths)")

# ============================================================
# PROBE 10: BOS — clean bullish break, close above prior swing high
# ============================================================
from copilot.detectors.bos import detect_bos
rows = [bar(100, 101, 99, 100.2) for _ in range(8)]
rows += [bar(100, 100.4, 96.0, 96.5)]                 # low A=96
rows += [bar(96.5, 97.5, 96.2, 97.2) for _ in range(3)]
rows += [bar(97.2, 102.0, 97.0, 101.5)]               # high B=102
rows += [bar(101.5, 101.8, 98.5, 99.0) for _ in range(3)]  # HL C=98.5
rows += [bar(99.0, 103.5, 98.9, 103.2)]               # close 103.2 > B=102 -> BOS
rows += [bar(103.2, 103.8, 102.8, 103.4) for _ in range(3)]
df = mkdf(rows)
r = detect_bos(df, swing_lookback=3)
ok = any(e["type"] == "BOS" and e["direction"] == "bullish" and abs(e["broken_level"] - 102) < 1.5 for e in r["events"])
P("bos: clean bullish BOS at ~102 detected", ok, f"events={r['events']} latest_bias={r['latest_bias']}")

# ============================================================
# PROBE 11: FVG — basic 3-candle gap with known boundaries
# ============================================================
from copilot.detectors.fvg import detect_fvg
rows = [bar(100, 101, 99, 100.5) for _ in range(15)]
rows += [bar(100.5, 101.0, 100.0, 100.8)]   # C0 high=101
rows += [bar(100.8, 106.0, 100.7, 105.8)]   # C1 impulse
rows += [bar(105.8, 106.5, 103.0, 106.0)]   # C2 low=103 -> gap 101..103
rows += [bar(106.0, 106.8, 105.5, 106.3) for _ in range(3)]
df = mkdf(rows)
r = detect_fvg(df)
ok = any(f["type"] == "bullish" and abs(f["lower"] - 101) < 0.01 and abs(f["upper"] - 103) < 0.01 for f in r["fvgs"])
P("fvg: bullish gap 101-103 detected with exact bounds", ok, f"fvgs={r['fvgs'][:2]}")
