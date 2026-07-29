"""Probe batch 2: order_block, breaker, ifvg, rejection, VP, liquidity side-label, killzone."""
import os, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd

def mkdf(rows, freq="1h"):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, index=idx); df.index.name = "ts"
    if "volume" not in df.columns: df["volume"] = 100.0
    return df[["open", "high", "low", "close", "volume"]]

def bar(o, h, l, c, v=100.0): return {"open": o, "high": h, "low": l, "close": c, "volume": v}
P = lambda name, ok, detail: print(f"[{'PASS' if ok else 'FAIL'}] {name}\n       {detail}")

# ============================================================
# PROBE 12: order_block — swing-break OB, known lowest-low candle
# Swing high 105 (confirmed), retrace, lowest low 101 at known bar, close breaks 105.
# ============================================================
from copilot.detectors.order_block import detect_order_block
rows  = [bar(100, 100.8, 99.4, 100.3) for _ in range(8)]
rows += [bar(100.3, 105.0, 100.2, 104.5)]               # swing high 105 (idx 8)
rows += [bar(104.5, 104.8, 103.0, 103.3)]
rows += [bar(103.3, 103.5, 101.0, 101.4)]               # lowest low 101 (idx 10) = expected OB
rows += [bar(101.4, 102.5, 101.2, 102.3)]
rows += [bar(102.3, 106.5, 102.2, 106.2)]               # close 106.2 > 105 -> trigger (idx 12)
rows += [bar(106.2, 106.8, 105.8, 106.4) for _ in range(4)]
df = mkdf(rows)
r = detect_order_block(df, swing_lookback=3)
ok = any(o["type"] == "bullish" and abs(o["low"] - 101.0) < 0.01 for o in r["obs"])
P("order_block: bullish OB = lowest-low candle (low 101) after swing break",
  ok, f"obs={r['obs'][:2]}")

# ============================================================
# PROBE 13: breaker_block — OB pierced by plain CLOSE below (no FVG on the way down)
# Standard SMC: close through the OB zone flips it to a breaker. Code requires an FVG.
# ============================================================
from copilot.detectors.breaker_block import detect_breaker_block
rows  = [bar(100, 101, 99, 100.2) for _ in range(16)]
rows += [bar(100.2, 100.4, 98.0, 98.2)]                 # bearish OB candle (idx 16)
rows += [bar(98.2, 104.0, 98.1, 103.8)]                 # bullish impulse > 1.5 ATR, closes above high
rows += [bar(103.8, 104.2, 102.0, 102.3)]
# grind back down THROUGH the OB zone with overlapping candles (no FVG):
for px in (101.0, 99.8, 98.6, 97.4, 96.6):
    rows += [bar(px + 1.0, px + 1.5, px - 0.6, px)]     # each closes lower, ranges overlap
rows += [bar(96.6, 97.0, 95.8, 96.2) for _ in range(3)]
df = mkdf(rows)
r = detect_breaker_block(df)
P("breaker_block: OB closed-through (no FVG) still flips to breaker",
  r["count"] > 0, f"count={r['count']} (code demands an FVG below ob_low to register the pierce)")

# ============================================================
# PROBE 14: ifvg — bullish FVG fully pierced by close -> bearish IFVG
# ============================================================
from copilot.detectors.ifvg import detect_ifvg
rows  = [bar(100, 101, 99, 100.5) for _ in range(15)]
rows += [bar(100.5, 101.0, 100.0, 100.8)]               # C0 high 101
rows += [bar(100.8, 106.0, 100.7, 105.8)]               # C1
rows += [bar(105.8, 106.5, 103.0, 106.0)]               # C2 low 103 -> bullish FVG 101..103
rows += [bar(106.0, 106.2, 104.0, 104.3)]
rows += [bar(104.3, 104.5, 100.2, 100.5)]               # closes 100.5 < 101 -> full pierce
rows += [bar(100.5, 101.5, 100.0, 100.8) for _ in range(3)]
df = mkdf(rows)
r = detect_ifvg(df)
ok = any(z["type"] == "bearish" and abs(z["lower"] - 101) < 0.01 and abs(z["upper"] - 103) < 0.01 for z in r["ifvgs"])
P("ifvg: pierced bullish FVG returns as bearish IFVG 101-103", ok, f"ifvgs={r['ifvgs'][:2]}")

# ============================================================
# PROBE 15: rejection_block — engulfing per docstring vs close-only check
# C1 bullish body 100->103; C2 opens GAP UP at 105, closes 99.5 (below C1 body low).
# Docstring says body must engulf; close-only check also fires when C2 body
# does NOT cover C1 body top. Construct C2 body [99.5..100.5] (open 100.5!) --
# actually test the documented pattern fires:
# ============================================================
from copilot.detectors.rejection_block import detect_rejection_block
rows  = [bar(100, 101, 99, 100.4) for _ in range(15)]
rows += [bar(100.0, 103.5, 99.8, 103.0)]                # C1 bullish body 100->103
rows += [bar(100.2, 100.4, 99.0, 99.4)]                 # C2 closes below 100 but body [99.4..100.2] engulfs nothing
rows += [bar(99.4, 100.0, 98.8, 99.2) for _ in range(3)]
df = mkdf(rows)
r = detect_rejection_block(df)
P("rejection_block: fires even when C2 body does NOT engulf C1 body (close-only test)",
  r["count"] > 0, f"count={r['count']} blocks={r['blocks'][:1]} (docstring demands full body engulf)")

# ============================================================
# PROBE 16: volume_profile — POC where the volume actually is
# 40 bars at 100 +/- 1 with vol 500; 10 bars at 110 +/- 1 with vol 50.
# ============================================================
from copilot.detectors.volume_profile import detect_volume_profile
rows  = [bar(100 + (i % 3 - 1) * 0.3, 101, 99, 100 + (i % 3 - 1) * 0.2, v=500) for i in range(40)]
rows += [bar(110 + (i % 3 - 1) * 0.3, 111, 109, 110 + (i % 3 - 1) * 0.2, v=50) for i in range(10)]
df = mkdf(rows)
r = detect_volume_profile(df)
P("volume_profile: POC inside the 99-101 high-volume area", 99 <= r["poc"] <= 101,
  f"poc={r['poc']} vah={r['vah']} val={r['val']} location={r['current_price_location']}")

# ============================================================
# PROBE 17: liquidity — wide bullish bar crossing a swing-high level
# reports a 'sellside' sweep of that high (side label from geometry, not pool type)
# ============================================================
from copilot.detectors.liquidity import detect_liquidity
rows  = [bar(100, 101, 99, 100.5) for _ in range(10)]
rows += [bar(100.5, 104, 100.4, 103.5)]                 # swing high 104
rows += [bar(103.5, 103.8, 101.0, 101.5) for _ in range(5)]
rows += [bar(101.5, 106, 101.4, 105.8)]                 # wide bar opens below 104, closes above
rows += [bar(105.8, 106.2, 105.0, 105.5) for _ in range(3)]
df = mkdf(rows)
r = detect_liquidity(df, lookback=30)
bogus = [s for s in r["recent_sweeps"] if s["side"] == "sellside" and abs(s["swept_level"] - 104) < 0.5]
P("liquidity: no 'sellside sweep' reported AT a swing-HIGH level",
  not bogus, f"bogus={bogus}")

# ============================================================
# PROBE 18: market_structure on flat market (every bar identical)
# ============================================================
from copilot.detectors.market_structure import detect_market_structure
df = mkdf([bar(100, 101, 99, 100) for _ in range(40)])
r = detect_market_structure(df)
P("market_structure: flat market -> ranging, no spurious swings",
  r["state"] == "ranging", f"state={r['state']} last_high={r['last_swing_high']} last_low={r['last_swing_low']}")

# ============================================================
# PROBE 19: current_killzone on a Saturday
# ============================================================
from copilot.detectors.sessions import current_killzone
from datetime import datetime
import pytz
sat = pytz.timezone("Europe/Kyiv").localize(datetime(2026, 6, 13, 9, 30))  # Saturday
r = current_killzone(sat)
P("sessions: Saturday 09:30 not reported as active London killzone",
  r["active_killzone"] is None, f"{r}")
