"""Empirical check: what does the smartmoneyconcepts library itself return
on the June 2026 probe fixtures? Run before wrapping it (P0-3)."""
import contextlib
import io
import sys

import numpy as np
import pandas as pd

with contextlib.redirect_stdout(io.StringIO()):
    from smartmoneyconcepts import smc


def mkdf(rows, freq="1h"):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, index=idx)
    df.index.name = "ts"
    if "volume" not in df.columns:
        df["volume"] = 100.0
    return df[["open", "high", "low", "close", "volume"]]


def bar(o, h, l, c, v=100.0):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def show_swings(shl, df):
    out = []
    hl = shl["HighLow"].values
    lv = shl["Level"].values
    for i in range(len(df)):
        if not np.isnan(hl[i]):
            out.append((i, "H" if hl[i] == 1 else "L", float(lv[i])))
    return out


# ── Probe 1 fixture: uptrend with pullback ──────────────────────────────
rows = []
for leg in range(4):
    base = 100 + leg * 10
    for j in range(5):
        rows.append(bar(base + j*2, base + j*2 + 2.2, base + j*2 - 0.4, base + j*2 + 2))
    for j in range(3):
        top = base + 10
        rows.append(bar(top - j*1.5, top - j*1.5 + 0.5, top - j*1.5 - 1.7, top - j*1.5 - 1.5))
last_top = 140
for j in range(3):
    rows.append(bar(last_top - j*1.2, last_top - j*1.2 + 0.3, last_top - j*1.2 - 1.4, last_top - j*1.2 - 1.2))
df1 = mkdf(rows)
shl = smc.swing_highs_lows(df1, swing_length=2)
ev = smc.bos_choch(df1, shl, close_break=True)
print("P1 uptrend-pullback swings:", show_swings(shl, df1))
nz = ev[(ev["BOS"].notna()) | (ev["CHOCH"].notna())]
print("P1 events:\n", nz)

# ── Probe 10 fixture: clean bullish BOS at 102 ──────────────────────────
rows = [bar(100, 101, 99, 100.2) for _ in range(8)]
rows += [bar(100, 100.4, 96.0, 96.5)]
rows += [bar(96.5, 97.5, 96.2, 97.2) for _ in range(3)]
rows += [bar(97.2, 102.0, 97.0, 101.5)]
rows += [bar(101.5, 101.8, 98.5, 99.0) for _ in range(3)]
rows += [bar(99.0, 103.5, 98.9, 103.2)]
rows += [bar(103.2, 103.8, 102.8, 103.4) for _ in range(3)]
df10 = mkdf(rows)
shl = smc.swing_highs_lows(df10, swing_length=3)
ev = smc.bos_choch(df10, shl, close_break=True)
print("\nP10 BOS swings:", show_swings(shl, df10))
nz = ev[(ev["BOS"].notna()) | (ev["CHOCH"].notna())]
print("P10 events:\n", nz)

# ── Probe 12 fixture: bullish OB, lowest-low 101 ────────────────────────
rows = [bar(100, 100.8, 99.4, 100.3) for _ in range(8)]
rows += [bar(100.3, 105.0, 100.2, 104.5)]
rows += [bar(104.5, 104.8, 103.0, 103.3)]
rows += [bar(103.3, 103.5, 101.0, 101.4)]
rows += [bar(101.4, 102.5, 101.2, 102.3)]
rows += [bar(102.3, 106.5, 102.2, 106.2)]
rows += [bar(106.2, 106.8, 105.8, 106.4) for _ in range(4)]
df12 = mkdf(rows)
shl = smc.swing_highs_lows(df12, swing_length=3)
print("\nP12 OB swings:", show_swings(shl, df12))
ob = smc.ob(df12, shl)
nz = ob[ob["OB"].notna()]
print("P12 obs:\n", nz)

# ── Probe 18: flat market ───────────────────────────────────────────────
df18 = mkdf([bar(100, 101, 99, 100) for _ in range(40)])
shl = smc.swing_highs_lows(df18, swing_length=5)
ev = smc.bos_choch(df18, shl, close_break=True)
print("\nP18 flat swings:", show_swings(shl, df18))
nz = ev[(ev["BOS"].notna()) | (ev["CHOCH"].notna())]
print("P18 events count:", len(nz))

# ── Probe 7/17 liquidity fixtures ───────────────────────────────────────
rows = [bar(100, 101, 99, 100.5) for _ in range(10)]
rows += [bar(100.5, 104, 100.4, 103.5)]
rows += [bar(103.5, 103.8, 101.0, 101.5) for _ in range(5)]
rows += [bar(101.5, 106, 101.4, 105.8)]   # closes above 104 = break
rows += [bar(105.8, 106.2, 105.0, 105.5) for _ in range(3)]
df7 = mkdf(rows)
shl = smc.swing_highs_lows(df7, swing_length=3)
print("\nP7 break swings:", show_swings(shl, df7))
liq = smc.liquidity(df7, shl)
print("P7 liquidity rows:\n", liq[liq["Liquidity"].notna()])

rows2 = rows[:17]
rows2 += [bar(101.5, 104.6, 101.3, 101.8)]  # wick sweep, closes back
rows2 += [bar(101.8, 102.2, 101.2, 101.6) for _ in range(3)]
df7b = mkdf(rows2)
shl = smc.swing_highs_lows(df7b, swing_length=3)
print("\nP7b sweep swings:", show_swings(shl, df7b))
liq = smc.liquidity(df7b, shl)
print("P7b liquidity rows:\n", liq[liq["Liquidity"].notna()])
