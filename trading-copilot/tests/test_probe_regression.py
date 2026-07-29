"""Regression suite converted from probes/*.py (P1-1, June 2026).

Each test encodes a June-2026 empirical probe as an assertion of *correct*
behaviour on an explicitly-constructed fixture (Working Rules: behavioural
tests, never schema-shape). The probe number and source file are noted per test.

Probes whose correct behaviour is not yet implemented (quarantined or P2-tier
detectors) are marked ``xfail(strict=True)``: they keep the suite green while
documenting the known bug, and will flip to XPASS — failing loudly — the moment
the fix lands, prompting removal of the marker. See DETECTOR_REVIEW_2026-06-10.md
and PLAN.md (Course Correction #2) for the root causes (R1–R5).
"""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest
import pytz


# ── fixture helpers (mirror probes/probe_detectors*.py) ────────────────────────

def _mkdf(rows: list[dict], freq: str = "1h") -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, index=idx)
    df.index.name = "ts"
    if "volume" not in df.columns:
        df["volume"] = 100.0
    return df[["open", "high", "low", "close", "volume"]]


def _bar(o: float, h: float, l: float, c: float, v: float = 100.0) -> dict:
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


# ── market structure (probes 1, 18) ────────────────────────────────────────────

def _uptrend_pullback_df() -> pd.DataFrame:
    """4 up-legs with shallow pullbacks (HH/HL intact), ending mid-pullback."""
    rows: list[dict] = []
    for leg in range(4):
        base = 100 + leg * 10
        for j in range(5):  # impulse up
            rows.append(_bar(base + j * 2, base + j * 2 + 2.2, base + j * 2 - 0.4, base + j * 2 + 2))
        for j in range(3):  # shallow pullback, higher low preserved
            top = base + 10
            rows.append(_bar(top - j * 1.5, top - j * 1.5 + 0.5, top - j * 1.5 - 1.7, top - j * 1.5 - 1.5))
    last_top = 140
    for j in range(3):  # final pullback in progress
        rows.append(_bar(last_top - j * 1.2, last_top - j * 1.2 + 0.3, last_top - j * 1.2 - 1.4, last_top - j * 1.2 - 1.2))
    return _mkdf(rows)


def test_market_structure_stays_bullish_in_pullback():
    """Probe 1: a normal retracement inside HH/HL must not flip bias to ranging."""
    from copilot.detectors.market_structure import detect_market_structure

    ms = detect_market_structure(_uptrend_pullback_df(), swing_lookback=2)
    assert ms["state"] == "bullish"


def test_market_structure_flat_market_is_ranging():
    """Probe 18: identical bars → ranging, no spurious swings."""
    from copilot.detectors.market_structure import detect_market_structure

    df = _mkdf([_bar(100, 101, 99, 100) for _ in range(40)])
    assert detect_market_structure(df)["state"] == "ranging"


# ── BOS (probe 10) ──────────────────────────────────────────────────────────────

def test_bos_clean_bullish_break_detected():
    """Probe 10: close above a confirmed prior swing high ~102 → bullish BOS."""
    from copilot.detectors.bos import detect_bos

    rows = [_bar(100, 101, 99, 100.2) for _ in range(8)]
    rows += [_bar(100, 100.4, 96.0, 96.5)]                      # low A = 96
    rows += [_bar(96.5, 97.5, 96.2, 97.2) for _ in range(3)]
    rows += [_bar(97.2, 102.0, 97.0, 101.5)]                    # high B = 102
    rows += [_bar(101.5, 101.8, 98.5, 99.0) for _ in range(3)]  # HL C = 98.5
    rows += [_bar(99.0, 103.5, 98.9, 103.2)]                    # close 103.2 > 102 → BOS
    rows += [_bar(103.2, 103.8, 102.8, 103.4) for _ in range(3)]
    r = detect_bos(_mkdf(rows), swing_lookback=3)
    assert any(
        e["type"] == "BOS" and e["direction"] == "bullish" and abs(e["broken_level"] - 102) < 1.5
        for e in r["events"]
    )


# ── FVG / IFVG (probes 11, 14) ──────────────────────────────────────────────────

def test_fvg_exact_bounds():
    """Probe 11: a 3-candle bullish gap is reported with exact 101–103 bounds."""
    from copilot.detectors.fvg import detect_fvg

    rows = [_bar(100, 101, 99, 100.5) for _ in range(15)]
    rows += [_bar(100.5, 101.0, 100.0, 100.8)]   # C0 high = 101
    rows += [_bar(100.8, 106.0, 100.7, 105.8)]   # C1 impulse
    rows += [_bar(105.8, 106.5, 103.0, 106.0)]   # C2 low = 103 → gap 101..103
    rows += [_bar(106.0, 106.8, 105.5, 106.3) for _ in range(3)]
    r = detect_fvg(_mkdf(rows))
    assert any(
        f["type"] == "bullish" and abs(f["lower"] - 101) < 0.01 and abs(f["upper"] - 103) < 0.01
        for f in r["fvgs"]
    )


def test_ifvg_pierced_bullish_fvg_returns_bearish():
    """Probe 14: a bullish FVG pierced by a close flips to a bearish IFVG 101–103."""
    from copilot.detectors.ifvg import detect_ifvg

    rows = [_bar(100, 101, 99, 100.5) for _ in range(15)]
    rows += [_bar(100.5, 101.0, 100.0, 100.8)]   # C0 high 101
    rows += [_bar(100.8, 106.0, 100.7, 105.8)]   # C1
    rows += [_bar(105.8, 106.5, 103.0, 106.0)]   # C2 low 103 → bullish FVG 101..103
    rows += [_bar(106.0, 106.2, 104.0, 104.3)]
    rows += [_bar(104.3, 104.5, 100.2, 100.5)]   # closes 100.5 < 101 → full pierce
    rows += [_bar(100.5, 101.5, 100.0, 100.8) for _ in range(3)]
    r = detect_ifvg(_mkdf(rows))
    assert any(
        z["type"] == "bearish" and abs(z["lower"] - 101) < 0.01 and abs(z["upper"] - 103) < 0.01
        for z in r["ifvgs"]
    )


# ── order block (probe 12) ──────────────────────────────────────────────────────

def test_order_block_lowest_low_after_swing_break():
    """Probe 12 (R1): bullish OB = lowest-low candle (low 101) before the break."""
    from copilot.detectors.order_block import detect_order_block

    rows = [_bar(100, 100.8, 99.4, 100.3) for _ in range(8)]
    rows += [_bar(100.3, 105.0, 100.2, 104.5)]   # swing high 105
    rows += [_bar(104.5, 104.8, 103.0, 103.3)]
    rows += [_bar(103.3, 103.5, 101.0, 101.4)]   # lowest low 101 = expected OB
    rows += [_bar(101.4, 102.5, 101.2, 102.3)]
    rows += [_bar(102.3, 106.5, 102.2, 106.2)]   # close 106.2 > 105 → trigger
    rows += [_bar(106.2, 106.8, 105.8, 106.4) for _ in range(4)]
    r = detect_order_block(_mkdf(rows), swing_lookback=3)
    assert any(o["type"] == "bullish" and abs(o["low"] - 101.0) < 0.01 for o in r["obs"])


# ── fractals (P2-1: swept vs broken close-back semantics) ───────────────────────

def _fractal_high_df(break_close: float) -> pd.DataFrame:
    """A 5-bar fractal swing high at 105 (2 lower highs each side), then a later
    bar that wicks to 106; its close (``break_close``) decides sweep (closes back
    ≤105) vs break (>105)."""
    rows = [
        _bar(100.0, 101.0, 99.0, 100.2),   # i=0 high 101  (left-2)
        _bar(100.2, 103.0, 100.1, 102.5),  # i=1 high 103  (left-1)
        _bar(102.5, 105.0, 102.0, 104.5),  # i=2 fractal high = 105 (center)
        _bar(104.5, 104.0, 103.0, 103.5),  # i=3 high 104  (right-1)
        _bar(103.5, 103.8, 102.5, 103.0),  # i=4 high 103.8 (right-2)
        _bar(103.0, 106.0, 102.9, break_close),  # i=5 wick to 106 above 105
        _bar(103.0, 104.0, 102.5, 103.2),
        _bar(103.2, 103.5, 102.0, 102.8),
    ]
    return _mkdf(rows)


def _find_fractal(result: dict, price: float) -> dict | None:
    return next((f for f in result["fractals"] if abs(f["price"] - price) < 0.5), None)


def test_fractal_wick_sweep_is_swept_not_broken():
    """A wick above the fractal that closes back below is a sweep, not a break."""
    from copilot.detectors.fractals import detect_fractals

    f = _find_fractal(detect_fractals(_fractal_high_df(break_close=103.8)), 105)
    assert f is not None and f["is_swept"] and not f["is_broken"]


def test_fractal_close_through_is_broken_not_swept():
    """A candle that CLOSES above the fractal is a structural break, not a sweep."""
    from copilot.detectors.fractals import detect_fractals

    f = _find_fractal(detect_fractals(_fractal_high_df(break_close=105.8)), 105)
    assert f is not None and f["is_broken"] and not f["is_swept"]


def test_fractal_width_3bar_vs_5bar():
    """A pivot with only 1 lower bar each side is a 3-bar fractal but NOT a 5-bar
    one when a higher high sits two bars away."""
    from copilot.detectors.fractals import detect_fractals

    rows = [
        _bar(105.5, 106.0, 105.0, 105.5),  # i=0 high 106 — taller than the center, 2 bars left
        _bar(101.0, 102.0, 100.0, 101.5),  # i=1 high 102
        _bar(101.5, 105.0, 101.0, 104.5),  # i=2 high 105 (3-bar pivot vs i1/i3)
        _bar(104.5, 104.0, 103.0, 103.5),  # i=3 high 104
        _bar(103.5, 103.8, 103.0, 103.2),  # i=4 high 103.8
        _bar(103.2, 103.5, 102.0, 102.8),  # i=5
    ]
    df = _mkdf(rows)
    assert _find_fractal(detect_fractals(df, bars="3"), 105) is not None
    assert _find_fractal(detect_fractals(df, bars="5"), 105) is None  # i0's 106 disqualifies it


# ── liquidity (probes 7, 7b, 17) ────────────────────────────────────────────────

def test_liquidity_close_through_break_not_reported_as_sweep():
    """Probe 7: a candle that CLOSES through a swing high is a break, not a sweep."""
    from copilot.detectors.liquidity import detect_liquidity

    rows = [_bar(100, 101, 99, 100.5) for _ in range(10)]
    rows += [_bar(100.5, 104, 100.4, 103.5)]                   # swing high 104
    rows += [_bar(103.5, 103.8, 101.0, 101.5) for _ in range(5)]
    rows += [_bar(101.5, 106, 101.4, 105.8)]                   # CLOSES above 104 = break
    rows += [_bar(105.8, 106.2, 105.0, 105.5) for _ in range(3)]
    r = detect_liquidity(_mkdf(rows), lookback=30)
    assert not any(
        s["side"] == "buyside" and abs(s["swept_level"] - 104) < 0.5 for s in r["recent_sweeps"]
    )


def test_liquidity_genuine_wick_sweep_reported():
    """Probe 7b: a wick above 104 that closes back below IS a buyside sweep."""
    from copilot.detectors.liquidity import detect_liquidity

    rows = [_bar(100, 101, 99, 100.5) for _ in range(10)]
    rows += [_bar(100.5, 104, 100.4, 103.5)]                   # swing high 104
    rows += [_bar(103.5, 103.8, 101.0, 101.5) for _ in range(5)]
    rows = rows[:16]                                           # only bars before any break
    rows += [_bar(101.5, 104.6, 101.3, 101.8)]                # wick sweep, closes back
    rows += [_bar(101.8, 102.2, 101.2, 101.6) for _ in range(3)]
    r = detect_liquidity(_mkdf(rows), lookback=30)
    assert any(
        s["side"] == "buyside" and abs(s["swept_level"] - 104) < 0.5 for s in r["recent_sweeps"]
    )


def test_liquidity_no_sellside_sweep_at_a_swing_high():
    """Probe 17 (R4): a wide bar crossing a swing HIGH must not print a 'sellside'
    sweep of that high — sweep side comes from pool type, not bar geometry."""
    from copilot.detectors.liquidity import detect_liquidity

    rows = [_bar(100, 101, 99, 100.5) for _ in range(10)]
    rows += [_bar(100.5, 104, 100.4, 103.5)]                   # swing high 104
    rows += [_bar(103.5, 103.8, 101.0, 101.5) for _ in range(5)]
    rows += [_bar(101.5, 106, 101.4, 105.8)]                   # wide bar opens below 104, closes above
    rows += [_bar(105.8, 106.2, 105.0, 105.5) for _ in range(3)]
    r = detect_liquidity(_mkdf(rows), lookback=30)
    assert not [
        s for s in r["recent_sweeps"] if s["side"] == "sellside" and abs(s["swept_level"] - 104) < 0.5
    ]


def test_liquidity_insufficient_data():
    """Edge case preserved from the deleted vacuous liquidity test file."""
    from copilot.detectors.liquidity import detect_liquidity

    df = _mkdf([_bar(100, 101, 99, 100.5), _bar(100.5, 102, 100, 101.5)])
    assert detect_liquidity(df).get("status") == "insufficient_data"


# ── cumulative delta (probes 2, 3) ──────────────────────────────────────────────

def test_cd_breakout_not_labeled_sweep():
    """Probe 2 (R5): a strong close above prior highs on positive delta is a
    breakout — no sweep_confirmation."""
    from copilot.detectors.cumulative_delta import detect_cumulative_delta

    rows = [_bar(100 + i * 0.1, 100.5 + i * 0.1, 99.5 + i * 0.1, 100.2 + i * 0.1) for i in range(30)]
    rows.append(_bar(103.2, 106.02, 103.0, 106.0))  # closes at the top, tiny wick
    df = _mkdf(rows)
    df["buy_vol"] = 80.0
    df["sell_vol"] = 20.0
    df["delta"] = 60.0
    assert detect_cumulative_delta(df).get("sweep_confirmation") is None


def test_cd_swing_to_swing_bearish_divergence():
    """Probe 3 (R5): price prints its highest high two bars back with falling CD —
    divergence must fire even though the last bar is not the extreme."""
    from copilot.detectors.cumulative_delta import detect_cumulative_delta

    rows = [_bar(100, 101, 99, 100.5) for _ in range(20)]
    rows.append(_bar(100.5, 105, 100.4, 104.5))    # push high, strong delta
    rows.append(_bar(104.5, 105.2, 103.0, 103.5))  # top 1
    rows.append(_bar(103.5, 105.3, 103.2, 103.6))  # top 2: HH, weaker CD
    rows.append(_bar(103.6, 103.8, 102.5, 102.8))
    rows.append(_bar(102.8, 103.0, 102.0, 102.2))  # last bar — not the extreme
    df = _mkdf(rows)
    df["delta"] = [10] * 20 + [500, 50, -200, -50, -30]
    df["buy_vol"] = 0.0
    df["sell_vol"] = 0.0
    r = detect_cumulative_delta(df)
    assert any(d["type"] == "bearish" for d in r["divergences"])


# ── sponsored candle / mitigation block (probe 8; P2-2 R3 single-OB + R4 pool sweep) ──

def _sponsored_bullish_df() -> pd.DataFrame:
    """Sellside POOL (swing low 100) swept by the OB candle (wick to 99, closes
    back), then an impulse closes above the prior swing high 104 → swing-break
    bullish OB at the sweep candle = a sponsored candle."""
    return _mkdf([
        _bar(100.0, 101.0, 99.5, 100.5),
        _bar(100.5, 104.0, 100.0, 103.5),   # swing high 104 (broken later)
        _bar(103.5, 104.0, 102.5, 103.0),
        _bar(103.0, 103.2, 101.0, 101.5),   # pullback
        _bar(101.5, 101.8, 100.0, 100.2),   # sellside POOL = swing low 100
        _bar(100.2, 102.0, 100.1, 101.8),   # bounce confirms the pool
        _bar(101.8, 102.2, 101.0, 101.2),
        _bar(101.2, 101.5, 99.0, 100.5),    # SWEEP of 100 (wick 99, closes back) + OB candle
        _bar(100.5, 105.0, 100.4, 104.5),   # impulse closes > 104 → bullish OB
        _bar(104.5, 105.0, 103.5, 104.0),
        _bar(104.0, 104.5, 103.0, 103.5),
        _bar(103.5, 104.0, 103.0, 103.6),
    ])


def _mitigation_bullish_df() -> pd.DataFrame:
    """Same break, but the shallow pullback (low 101.5) never reaches the prior
    pool — the bullish OB forms WITHOUT a prior sellside sweep → mitigation block,
    not sponsored."""
    return _mkdf([
        _bar(100.0, 101.0, 99.5, 100.5),
        _bar(100.5, 104.0, 100.0, 103.5),   # swing high 104
        _bar(103.5, 104.0, 102.5, 103.0),
        _bar(103.0, 103.2, 101.5, 101.8),   # shallow pullback (no sweep of the pool)
        _bar(101.8, 102.0, 101.2, 101.5),   # swing low 101.2
        _bar(101.5, 102.0, 101.3, 101.9),
        _bar(101.9, 105.0, 101.8, 104.6),   # impulse closes > 104 → bullish OB, no sweep
        _bar(104.6, 105.0, 103.5, 104.0),
        _bar(104.0, 104.5, 103.0, 103.5),
        _bar(103.5, 104.0, 103.0, 103.6),
        _bar(103.6, 104.0, 103.0, 103.4),
        _bar(103.4, 103.8, 103.0, 103.5),
    ])


def test_sponsored_candle_pool_sweep_detected():
    """Probe 8 (R3/R4): a swing-break OB preceded by a sweep of the nearest prior
    liquidity pool (not the OB's own boundary) is a sponsored candle."""
    from copilot.detectors.sponsored_candle import detect_sponsored_candle

    r = detect_sponsored_candle(_sponsored_bullish_df(), lookback=30, sweep_window=5, swing_lookback=2)
    assert r["count"] > 0
    c = r["candles"][0]
    assert c["ob_type"] == "bullish" and c["sweep_side"] == "sellside"
    assert abs(c["pool_price"] - 100.0) < 0.5


def test_mitigation_block_requires_no_prior_sweep():
    """R3/R4: an OB that broke structure without first sweeping the prior pool is a
    mitigation block — and must NOT be reported as a sponsored candle."""
    from copilot.detectors.mitigation_block import detect_mitigation_block
    from copilot.detectors.sponsored_candle import detect_sponsored_candle

    df = _mitigation_bullish_df()
    assert detect_sponsored_candle(df, sweep_window=5, swing_lookback=2)["count"] == 0
    mb = detect_mitigation_block(df, sweep_window=5, swing_lookback=2)
    assert mb["count"] > 0 and mb["blocks"][0]["type"] == "bullish"


# ── volume profile (probe 16) ───────────────────────────────────────────────────

def test_volume_profile_poc_in_high_volume_area():
    """Probe 16: POC sits in the 99–101 band where ~95% of volume traded."""
    from copilot.detectors.volume_profile import detect_volume_profile

    rows = [_bar(100 + (i % 3 - 1) * 0.3, 101, 99, 100 + (i % 3 - 1) * 0.2, v=500) for i in range(40)]
    rows += [_bar(110 + (i % 3 - 1) * 0.3, 111, 109, 110 + (i % 3 - 1) * 0.2, v=50) for i in range(10)]
    r = detect_volume_profile(_mkdf(rows))
    assert 99 <= r["poc"] <= 101


# ════════════════════════════════════════════════════════════════════════════════
# Known-broken: correct behaviour not yet implemented (xfail until the fix lands).
# ════════════════════════════════════════════════════════════════════════════════

def test_fib_zones_short_ote():
    """Probe 5: on a bearish 110→100 swing, price retraced to 107 sits inside the
    SHORT OTE (0.62–0.79 retracement up). The detector only models the long side."""
    from copilot.detectors.fib_zones import detect_fib_zones

    rows = [_bar(110 - i * 0.5, 110.2 - i * 0.5, 109.5 - i * 0.5, 109.8 - i * 0.5) for i in range(20)]
    rows.append(_bar(106.8, 107.2, 106.5, 107.0))  # 0.7 retracement of 110→100
    r = detect_fib_zones(_mkdf(rows), swing_high=110, swing_low=100)
    assert r["in_ote"]


@pytest.mark.xfail(strict=True, reason="P2-1: detect_compression fires on random walks (quarantined)")
def test_compression_low_false_positive_on_noise():
    """Probe 6: a volatility-squeeze detector must rarely fire on pure random walks.
    LRLR is a Low-Resistance Liquidity Run, not a variance contraction."""
    from copilot.detectors.compression import detect_compression

    rng = np.random.default_rng(7)
    hits = 0
    for _ in range(50):
        closes = 100 + np.cumsum(rng.normal(0, 0.5, 80))
        rows = []
        for c in closes:
            spread = abs(rng.normal(0, 0.6)) + 0.1
            rows.append(_bar(c, c + spread, c - spread, c + rng.normal(0, 0.2)))
        if detect_compression(_mkdf(rows))["count"] > 0:
            hits += 1
    assert hits / 50 < 0.2


@pytest.mark.xfail(strict=True, reason="P2: check_cd_absorption threshold passes below-average volume (quarantined)")
def test_cd_absorption_rejects_below_average_volume():
    """Probe 4 (R5): a quiet bar at 0.75× average volume is not absorption."""
    from copilot.detectors.orderflow_composite import check_cd_absorption

    rows = [_bar(100 + i * 0.05, 101 + i * 0.05, 99 + i * 0.05, 100.5 + i * 0.05, v=100) for i in range(29)]
    rows.append(_bar(101.4, 101.55, 101.35, 101.52, v=75))  # 25% below average volume
    assert not check_cd_absorption(_mkdf(rows))["absorption_detected"]


def test_multi_tf_ltf_ranging_is_coherent():
    """Probe 9: HTF bullish + LTF ranging should not collapse to the
    'unclear role / weak sync' default reserved for an HTF-ranging market."""
    from copilot.detectors.multi_tf import check_multi_tf_alignment

    r = check_multi_tf_alignment("bullish", "ranging", "4h", "15m")
    assert not (r["ltf_role"] == "unclear" and r["sync_quality"] == "weak")


def test_breaker_block_close_through_without_fvg():
    """Probe 13: an OB ground back through by overlapping closes (no FVG on the
    way down) still flips to a breaker block."""
    from copilot.detectors.breaker_block import detect_breaker_block

    rows = [_bar(100, 101, 99, 100.2) for _ in range(16)]
    rows += [_bar(100.2, 100.4, 98.0, 98.2)]   # bearish OB candle
    rows += [_bar(98.2, 104.0, 98.1, 103.8)]   # impulse > 1.5 ATR, closes above high
    rows += [_bar(103.8, 104.2, 102.0, 102.3)]
    for px in (101.0, 99.8, 98.6, 97.4, 96.6):  # grind down through the OB, ranges overlap (no FVG)
        rows += [_bar(px + 1.0, px + 1.5, px - 0.6, px)]
    rows += [_bar(96.6, 97.0, 95.8, 96.2) for _ in range(3)]
    assert detect_breaker_block(_mkdf(rows))["count"] > 0


@pytest.mark.xfail(strict=True, reason="P2-1: rejection_block quarantined indefinitely pending manual redefinition by the trader")
def test_rejection_block_requires_body_engulf():
    """Probe 15: C2 body [99.4..100.2] does NOT engulf C1 body [100..103], so no
    rejection block should form — the detector currently fires on close-through alone."""
    from copilot.detectors.rejection_block import detect_rejection_block

    rows = [_bar(100, 101, 99, 100.4) for _ in range(15)]
    rows += [_bar(100.0, 103.5, 99.8, 103.0)]   # C1 bullish body 100→103
    rows += [_bar(100.2, 100.4, 99.0, 99.4)]    # C2 closes below 100 but engulfs nothing
    rows += [_bar(99.4, 100.0, 98.8, 99.2) for _ in range(3)]
    assert detect_rejection_block(_mkdf(rows))["count"] == 0


def test_killzone_inactive_on_weekend():
    """Probe 19: Saturday 09:30 Kyiv is not an active London-open killzone."""
    from copilot.detectors.sessions import current_killzone

    sat = pytz.timezone("Europe/Kyiv").localize(datetime(2026, 6, 13, 9, 30))  # Saturday
    assert current_killzone(sat)["active_killzone"] is None
