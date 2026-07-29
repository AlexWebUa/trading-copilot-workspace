#!/usr/bin/env python3
"""
debug_detectors.py — fetch BTCUSDT spot data, run every detector,
and write one .pine file (+ one .json raw-result file) per detector
for TradingView visual debugging.

Usage (from trading-copilot/ directory):
    python scripts/debug_detectors.py                          # all detectors
    python scripts/debug_detectors.py --tf 1h --bars 500      # custom TF/bars
    python scripts/debug_detectors.py --detector detect_fvg   # single detector
    python scripts/debug_detectors.py --swing-lookback 3      # swing sensitivity
    python scripts/debug_detectors.py --list                   # names + audit status

Each output file can be pasted directly into TradingView:
    Pine Script Editor → New indicator → paste → Save → Add to chart
    (Switch chart to BTCUSDT and the matching timeframe first.)

The .json file next to each .pine holds the raw detector output —
cross-check every drawn level against it when verifying a detector.

Post P0-3/P0-5 (June 2026): market_structure / bos / order_block /
liquidity / cumulative_delta visualize the rewritten implementations
(smartmoneyconcepts-backed; structure events are close-break confirmed).
Detectors still quarantined from the LLM tool list are runnable here for
manual inspection but are tagged QUARANTINED — their output is known-bad
until their P2 rewrite lands.

Visual style: B&W design system (matches pine_script.py).
  c_fvg_fill     #f7525f 15%  — FVG / IFVG fill
  c_fvg_line     #f7525f 100% — FVG center line, IFVG border, bearish events
  c_block_active #4a4a4a 15%  — All blocks (active)
  c_block_mit    #4a4a4a 5%   — All blocks (mitigated)
  c_structure    #000000 100% — BOS, liquidity lines, swing markers
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Ensure the project root is on the path when run directly
_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from copilot.data.base import VALID_TIMEFRAMES
from copilot.data.binance import BinanceSource, fetch_ohlcv_with_delta
from copilot.detectors.absorption_poi import check_absorption_at_poi
from copilot.detectors.bos import detect_bos
from copilot.detectors.breaker_block import detect_breaker_block
from copilot.detectors.cd_divergence_structure import check_cd_divergence_at_structure
from copilot.detectors.compression import detect_compression
from copilot.detectors.cumulative_delta import detect_cumulative_delta
from copilot.detectors.fib_zones import detect_fib_zones
from copilot.detectors.fractals import detect_fractals
from copilot.detectors.fvg import detect_fvg
from copilot.detectors.ifvg import detect_ifvg
from copilot.detectors.liquidity import detect_liquidity
from copilot.detectors.market_structure import detect_market_structure
from copilot.detectors.mitigation_block import detect_mitigation_block
from copilot.detectors.multi_tf import check_multi_tf_alignment
from copilot.detectors.order_block import detect_order_block
from copilot.detectors.rejection_block import detect_rejection_block
from copilot.detectors.sessions import current_killzone
from copilot.detectors.sponsored_candle import detect_sponsored_candle
from copilot.detectors.volume_profile import detect_volume_profile

# HTF to use for multi-TF alignment check, keyed by LTF
_HTF_MAP: dict[str, str] = {
    "1m": "15m", "3m": "1h", "5m": "1h",
    "15m": "4h", "30m": "4h", "1h": "4h", "4h": "1d", "1d": "1d",
}

# Canonical order — used for --list and validation
_ALL_DETECTOR_NAMES: list[str] = [
    "detect_fvg",
    "detect_order_block",
    "detect_ifvg",
    "detect_breaker_block",
    "detect_rejection_block",
    "detect_mitigation_block",
    "detect_liquidity",
    "detect_bos",
    "detect_volume_profile",
    "detect_market_structure",
    "detect_fractals",
    "detect_fib_zones",
    "detect_compression",
    "detect_sponsored_candle",
    "check_absorption_at_poi",
    "detect_cumulative_delta",
    "check_cd_divergence_at_structure",
    "current_killzone",
    "check_multi_tf_alignment",
]

# Verification status per the June 2026 audit + P0-3/P0-5 rewrites.
# "REWRITTEN" = new implementation, needs fresh visual verification.
# "QUARANTINED" = removed from the LLM tool list, output known-bad (P2 rewrite).
_DETECTOR_STATUS: dict[str, str] = {
    "detect_fvg": "ok (audit-verified)",
    "detect_ifvg": "ok (audit-verified)",
    "detect_volume_profile": "ok (audit-verified)",
    "detect_market_structure": "REWRITTEN P0-3 — verify: state flips only on close-break events",
    "detect_bos": "REWRITTEN P0-3 — verify: every event line ends at a close through it",
    "detect_order_block": "REWRITTEN P0-3 — verify: OB = lowest-low/highest-high before the break",
    "detect_liquidity": "REWRITTEN P0-3 — verify: sweeps only at side-matching pools, close-back",
    "detect_cumulative_delta": "REWRITTEN P0-5 — verify: divergence at confirmed extreme; sweep = pool-anchored",
    "detect_fractals": "FIXED P2-1 — Williams 5-bar default; swept=wick+close-back, broken=close-through",
    "detect_fib_zones": "FIXED P2-1 — auto-infers leg direction; short OTE from swing low",
    "detect_rejection_block": "QUARANTINED — definition under manual revision by the trader (P2-1)",
    "detect_mitigation_block": "FIXED P2-2 — swing-break OB with no prior pool sweep",
    "detect_breaker_block": "FIXED P2-2 — swing-break OB, pierce = close through opposite side",
    "detect_sponsored_candle": "FIXED P2-2 — swing-break OB + sweep of nearest prior pool (R4)",
    "detect_compression": "QUARANTINED — fires on random walks (P2)",
    "check_absorption_at_poi": "QUARANTINED — broken volume threshold (P2)",
    "check_cd_divergence_at_structure": "QUARANTINED — last-bar divergence logic (P2)",
    "current_killzone": "FIXED P2-1 — weekend gate added",
    "check_multi_tf_alignment": "FIXED P2-1 — single coherent classification path",
}

_QUARANTINED = {n for n, s in _DETECTOR_STATUS.items() if s.startswith("QUARANTINED")}

# Detectors that need buy_vol/sell_vol/delta columns
_NEEDS_DELTA: frozenset[str] = frozenset({
    "detect_cumulative_delta",
    "check_cd_divergence_at_structure",
})

# Detectors that need a separate HTF OHLCV fetch
_NEEDS_HTF: frozenset[str] = frozenset({
    "check_multi_tf_alignment",
})

# Detectors that need ltf_ms_result (market-structure on LTF)
_NEEDS_MS: frozenset[str] = frozenset({
    "detect_fib_zones",
    "check_multi_tf_alignment",
})

# ── Pine Script helpers ───────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _header(symbol: str, tf: str, indicator_name: str, future_bars: int) -> list[str]:
    return [
        f"// Generated by debug_detectors.py — {symbol} {tf} — {indicator_name} — {_now_str()}",
        "//@version=5",
        f'indicator("Debug: {indicator_name} | {symbol} {tf}", overlay=true, '
        "max_boxes_count=500, max_lines_count=500, max_labels_count=500)",
        "",
        "// ── Design system — B&W preset ───────────────────────────────────────────────",
        "c_fvg_fill     = color.new(#f7525f, 85)   // FVG / IFVG fill (15%)",
        "c_fvg_line     = color.new(#f7525f,  0)   // FVG center line, IFVG border, bearish",
        "c_block_active = color.new(#4a4a4a, 85)   // Blocks active (15%)",
        "c_block_mit    = color.new(#4a4a4a, 95)   // Blocks mitigated (5%)",
        "c_structure    = color.new(#000000,  0)   // BOS, liquidity, swing markers",
        "c_vp_hvn       = color.new(#4a4a4a, 40)   // VP HVN bars",
        "c_vp_lvn       = color.new(#4a4a4a, 80)   // VP LVN bars",
        "c_vp_poc       = color.new(#f7525f, 35)   // VP POC bar",
        'show_labels    = input.bool(true, "Show labels")',
        'drop_forming   = input.bool(true, "Source data drops the forming bar (shift anchor left 1)")',
        "",
        "if barstate.islast",
        # All drawings anchor to `anchor`, the last CLOSED bar. The detector data
        # excludes the forming candle, but on a live chart barstate.islast fires on
        # the forming bar — so the script's last bar = bar_index-1. Without this the
        # whole overlay is shifted +1 bar to the right.
        "    anchor = bar_index - (drop_forming ? 1 : 0)",
    ]


def _ts_to_age(df: pd.DataFrame, ts_str: str) -> int:
    """Return how many bars ago *ts_str* occurred relative to the last bar."""
    try:
        ts = pd.Timestamp(ts_str)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        tf_sec = float((df.index[1] - df.index[0]).total_seconds())
        return max(1, int((df.index[-1] - ts).total_seconds() / tf_sec))
    except Exception:
        return 1


def _nothing(msg: str) -> list[str]:
    return [
        f'    label.new(anchor, close, "{msg}", '
        f'style=label.style_label_left, color=c_block_active, '
        f'textcolor=color.white, size=size.small)'
    ]


def _assemble(header: list[str], body: list[str]) -> str:
    return "\n".join(header + body)


# ── Per-detector Pine Script body generators ──────────────────────────────────
# Each function returns a list[str] of indented Pine Script lines (4-space).
# They go inside the `if barstate.islast` block produced by _header().

# ── FVG ──────────────────────────────────────────────────────────────────────

def _pine_fvg(result: dict, future_bars: int) -> list[str]:
    """
    B&W style: c_fvg_fill box (no border) + solid c_fvg_line center line.
    fill_state and fill_percentage shown in label (guarded by show_labels).
    """
    lines = []
    for z in result.get("fvgs", []):
        # age_bars anchors C2 (i+2); the gap belongs to the C1 impulse candle, so
        # shift the left edge one bar left to sit on C1.
        age      = max(1, int(z["age_bars"])) + 1
        top, bot = z["upper"], z["lower"]
        mid      = round((top + bot) / 2, 2)
        ztype    = z["type"]
        state    = z.get("fill_state", "untouched")
        pct      = z.get("fill_percentage", 0)
        arrow    = "↑" if ztype == "bullish" else "↓"
        # Fill box — no border
        lines.append(
            f'    box.new(anchor-{age}, {top}, anchor+{future_bars}, {bot}, '
            f'bgcolor=c_fvg_fill, border_color=color.new(color.white, 100))'
        )
        # Center line — distinguishes FVG from IFVG
        lines.append(
            f'    line.new(anchor-{age}, {mid}, anchor+{future_bars}, {mid}, '
            f'color=c_fvg_line, style=line.style_solid, width=1)'
        )
        # Debug label: fill state + fill %
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor-{age}+1, {top}, '
            f'"FVG{arrow} {state} {pct:.0f}%", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.tiny)'
        )
    return lines or _nothing("No FVGs detected")


# ── IFVG ─────────────────────────────────────────────────────────────────────

def _pine_ifvg(result: dict, future_bars: int) -> list[str]:
    """
    B&W style: c_fvg_fill box with DASHED c_fvg_line border. NO center line
    (dashed border is the visual distinction from FVG).
    """
    lines = []
    for z in result.get("ifvgs", []):
        # See _pine_fvg: anchor the box on the C1 gap candle, not C2.
        age      = max(1, int(z["age_bars"])) + 1
        top, bot = z["upper"], z["lower"]
        ztype    = z["type"]
        tested   = "tested" if z["is_tested"] else "untested"
        arrow    = "↑" if ztype == "bullish" else "↓"
        lines.append(
            f'    box.new(anchor-{age}, {top}, anchor+{future_bars}, {bot}, '
            f'bgcolor=c_fvg_fill, border_color=c_fvg_line, '
            f'border_style=line.style_dashed, border_width=1)'
        )
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor-{age}+1, {top}, "IFVG{arrow} {tested}", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.tiny)'
        )
    return lines or _nothing("No IFVGs detected")


# ── Order Blocks ──────────────────────────────────────────────────────────────

def _pine_order_block(result: dict, future_bars: int) -> list[str]:
    """
    Active: c_block_active (extends right).  Mitigated: c_block_mit (ends at anchor).
    has_fvg_after shown as +FVG suffix.
    """
    lines = []
    for z in result.get("obs", []):
        age      = max(1, int(z["age_bars"]))
        top, bot = z["high"], z["low"]
        ztype    = z["type"]
        mit      = z.get("is_mitigated", False)
        fvgm     = "+FVG" if z.get("has_fvg_after") else ""
        arrow    = "↑" if ztype == "bullish" else "↓"
        label    = f"OB{arrow}{fvgm}"
        if mit:
            lines.append(
                f'    box.new(anchor-{age}, {top}, anchor, {bot}, '
                f'bgcolor=c_block_mit, border_color=color.new(color.white, 100))'
            )
            lines.append(f'    if show_labels')
            lines.append(
                f'        label.new(anchor-{age}+1, {top}, "{label} mit", '
                f'color=color.new(color.white, 100), textcolor=color.black, '
                f'style=label.style_none, size=size.tiny)'
            )
        else:
            lines.append(
                f'    box.new(anchor-{age}, {top}, anchor+{future_bars}, {bot}, '
                f'bgcolor=c_block_active, border_color=color.new(color.white, 100))'
            )
            lines.append(f'    if show_labels')
            lines.append(
                f'        label.new(anchor-{age}+1, {top}, "{label}", '
                f'color=color.new(color.white, 100), textcolor=color.black, '
                f'style=label.style_none, size=size.tiny)'
            )
    return lines or _nothing("No Order Blocks detected")


# ── Breaker Blocks ────────────────────────────────────────────────────────────

def _pine_breaker_block(result: dict, future_bars: int) -> list[str]:
    """Same block pattern as OB — c_block_active / c_block_mit."""
    lines = []
    for z in result.get("breakers", []):
        age      = max(1, int(z["age_bars"]))
        top, bot = z["high"], z["low"]
        ztype    = z["type"]
        mit      = z.get("is_mitigated", False)
        tested   = " tested" if z.get("is_tested") else ""
        arrow    = "↑" if ztype == "bullish" else "↓"
        label    = f"BB{arrow}{tested}"
        if mit:
            lines.append(
                f'    box.new(anchor-{age}, {top}, anchor, {bot}, '
                f'bgcolor=c_block_mit, border_color=color.new(color.white, 100))'
            )
            lines.append(f'    if show_labels')
            lines.append(
                f'        label.new(anchor-{age}+1, {top}, "{label} mit", '
                f'color=color.new(color.white, 100), textcolor=color.black, '
                f'style=label.style_none, size=size.tiny)'
            )
        else:
            lines.append(
                f'    box.new(anchor-{age}, {top}, anchor+{future_bars}, {bot}, '
                f'bgcolor=c_block_active, border_color=color.new(color.white, 100))'
            )
            lines.append(f'    if show_labels')
            lines.append(
                f'        label.new(anchor-{age}+1, {top}, "{label}", '
                f'color=color.new(color.white, 100), textcolor=color.black, '
                f'style=label.style_none, size=size.tiny)'
            )
    return lines or _nothing("No Breaker Blocks detected")


# ── Rejection Blocks ──────────────────────────────────────────────────────────

def _pine_rejection_block(result: dict, future_bars: int) -> list[str]:
    """Same block pattern — c_block_active / c_block_mit."""
    lines = []
    for z in result.get("blocks", []):
        age      = max(1, int(z["age_bars"]))
        top, bot = z["high"], z["low"]
        ztype    = z["type"]
        mit      = z.get("is_mitigated", False)
        arrow    = "↑" if ztype == "bullish" else "↓"
        label    = f"RB{arrow}"
        if mit:
            lines.append(
                f'    box.new(anchor-{age}, {top}, anchor, {bot}, '
                f'bgcolor=c_block_mit, border_color=color.new(color.white, 100))'
            )
            lines.append(f'    if show_labels')
            lines.append(
                f'        label.new(anchor-{age}+1, {top}, "{label} mit", '
                f'color=color.new(color.white, 100), textcolor=color.black, '
                f'style=label.style_none, size=size.tiny)'
            )
        else:
            lines.append(
                f'    box.new(anchor-{age}, {top}, anchor+{future_bars}, {bot}, '
                f'bgcolor=c_block_active, border_color=color.new(color.white, 100))'
            )
            lines.append(f'    if show_labels')
            lines.append(
                f'        label.new(anchor-{age}+1, {top}, "{label}", '
                f'color=color.new(color.white, 100), textcolor=color.black, '
                f'style=label.style_none, size=size.tiny)'
            )
    return lines or _nothing("No Rejection Blocks detected")


# ── Mitigation Blocks ─────────────────────────────────────────────────────────

def _pine_mitigation_block(result: dict, future_bars: int) -> list[str]:
    """Same block pattern — c_block_active / c_block_mit."""
    lines = []
    for z in result.get("blocks", []):
        age      = max(1, int(z["age_bars"]))
        top, bot = z["high"], z["low"]
        ztype    = z["type"]
        mit      = z.get("is_mitigated", False)
        arrow    = "↑" if ztype == "bullish" else "↓"
        label    = f"MB{arrow}"
        if mit:
            lines.append(
                f'    box.new(anchor-{age}, {top}, anchor, {bot}, '
                f'bgcolor=c_block_mit, border_color=color.new(color.white, 100))'
            )
            lines.append(f'    if show_labels')
            lines.append(
                f'        label.new(anchor-{age}+1, {top}, "{label} mit", '
                f'color=color.new(color.white, 100), textcolor=color.black, '
                f'style=label.style_none, size=size.tiny)'
            )
        else:
            lines.append(
                f'    box.new(anchor-{age}, {top}, anchor+{future_bars}, {bot}, '
                f'bgcolor=c_block_active, border_color=color.new(color.white, 100))'
            )
            lines.append(f'    if show_labels')
            lines.append(
                f'        label.new(anchor-{age}+1, {top}, "{label}", '
                f'color=color.new(color.white, 100), textcolor=color.black, '
                f'style=label.style_none, size=size.tiny)'
            )
    return lines or _nothing("No Mitigation Blocks detected")


# ── Liquidity ─────────────────────────────────────────────────────────────────

def _pine_liquidity(result: dict, df: pd.DataFrame, future_bars: int) -> list[str]:
    """
    Unswept BSL/SSL: c_structure dashed line.
    Sweeps: c_structure solid line + ✕ marker at midpoint.
    Debug extra: touches count shown in label.
    """
    lines = []
    for pool in result.get("buyside_liquidity", []):
        age     = max(1, int(pool["age_bars"]))
        price   = pool["price"]
        touches = pool.get("touches", 0)
        lines.append(
            f'    line.new(anchor-{age}, {price}, anchor+{future_bars}, {price}, '
            f'color=c_structure, style=line.style_dashed, width=1)'
        )
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor-{age}+1, {price}, '
            f'"BSL {price} x{touches}", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.tiny)'
        )
    for pool in result.get("sellside_liquidity", []):
        age     = max(1, int(pool["age_bars"]))
        price   = pool["price"]
        touches = pool.get("touches", 0)
        lines.append(
            f'    line.new(anchor-{age}, {price}, anchor+{future_bars}, {price}, '
            f'color=c_structure, style=line.style_dashed, width=1)'
        )
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor-{age}+1, {price}, '
            f'"SSL {price} x{touches}", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.tiny)'
        )
    for sweep in result.get("recent_sweeps", []):
        try:
            ts = pd.Timestamp(sweep["sweep_ts"])
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            age_sweep = max(1, _ts_to_age(df, sweep["sweep_ts"]))
        except Exception:
            continue
        age_level = age_sweep + 10      # approximate fractal age
        mid_age   = (age_level + age_sweep) // 2
        level     = sweep["swept_level"]
        side_tag  = "BSL" if sweep["side"] == "buyside" else "SSL"
        closed    = sweep.get("closed_back", False)
        # Solid line from fractal to sweep bar
        lines.append(
            f'    line.new(anchor-{age_level}, {level}, anchor-{age_sweep}, {level}, '
            f'color=c_structure, style=line.style_solid, width=1)'
        )
        # ✕ marker at midpoint
        lines.append(
            f'    label.new(anchor-{mid_age}, {level}, "✕", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.small)'
        )
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor-{age_level}+1, {level}, '
            f'"{side_tag} swept{"·cb" if closed else ""}", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.tiny)'
        )
    return lines or _nothing("No liquidity levels detected")


# ── BOS / cBOS ────────────────────────────────────────────────────────────────

def _pine_bos(result: dict, df: pd.DataFrame, future_bars: int, swing_lookback: int = 5) -> list[str]:
    """
    All BOS / cBOS events, drawn the same way as _pine_market_structure: the line
    runs from the ACTUAL broken swing to the break candle (no synthetic +8 left
    edge), so every line starts at the fractal it broke and ends at the candle
    whose close crossed the level. Labels use style_none (no vertical pointer).
    c_structure solid line: 2px=BOS, 1px=cBOS. Debug extra: break-candle body/ATR.
    """
    if result.get("status"):
        return _nothing(f"BOS: {result['status']}")

    from copilot.detectors.smc_lib import lib_swings, structure_events, true_range_atr

    shl    = lib_swings(df, swing_lookback)
    events = structure_events(df, shl)   # oldest-first, with swing_idx / break_idx
    if not events:
        return _nothing("No BOS / cBOS events")

    opens  = df["open"].values
    closes = df["close"].values
    atr    = true_range_atr(df)
    n      = len(df)

    lines: list[str] = []
    for i, ev in enumerate(events):
        age_swing = max(1, n - 1 - ev["swing_idx"])
        age_break = max(1, n - 1 - ev["break_idx"])
        level     = round(ev["level"], 2)
        width     = 2 if ev["type"] == "BOS" else 1
        color     = "c_structure" if ev["direction"] == "bullish" else "c_fvg_line"
        arrow     = "↑" if ev["direction"] == "bullish" else "↓"
        j         = ev["break_idx"]
        av        = float(atr[j]) if atr[j] > 0 else 1.0
        body_atr  = round(abs(closes[j] - opens[j]) / av, 2)

        # Line: broken swing → break candle, at the broken level.
        lines.append(
            f'    line.new(anchor-{age_swing}, {level}, anchor-{age_break}, {level}, '
            f'color={color}, style=line.style_solid, width={width})'
        )
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor-{age_break}, {level}, '
            f'"{ev["type"]}{arrow} #{i+1} | {body_atr:.2f}xATR", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.tiny)'
        )

    # Summary label
    latest = result.get("latest_bias", "none")
    count  = result.get("count", len(events))
    lc     = "c_fvg_line" if latest == "bearish" else ("c_structure" if latest == "bullish" else "c_block_active")
    lines.append(
        f'    label.new(anchor+1, close, '
        f'"BOS: {count} events | bias: {latest}", '
        f'color={lc}, textcolor=color.white, style=label.style_label_left, size=size.small)'
    )
    return lines


# ── Volume Profile ────────────────────────────────────────────────────────────

def _pine_volume_profile(result: dict, bars: int, future_bars: int) -> list[str]:
    """
    B&W style: c_vp_poc for POC (dashed line + bar), c_vp_hvn/lvn for nodes.
    VAH/VAL as grey (#888) dashed lines.
    """
    if result.get("status"):
        return _nothing(f"Volume profile: {result['status']}")
    lines = []
    poc = result.get("poc")
    vah = result.get("vah")
    val = result.get("val")
    loc = result.get("current_price_location", "")
    left = bars - 1

    if poc:
        lines += [
            f'    line.new(anchor-{left}, {poc}, anchor+{future_bars}, {poc}, '
            f'color=c_vp_poc, style=line.style_dashed, width=1)',
        ]
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor, {poc}, "POC {poc} | {loc}", '
            f'color=c_vp_poc, textcolor=color.white, '
            f'style=label.style_label_left, size=size.small)'
        )
    for lvl, lbl in [(vah, "VAH"), (val, "VAL")]:
        if lvl:
            lines.append(
                f'    line.new(anchor-{left}, {lvl}, anchor+{future_bars}, {lvl}, '
                f'color=color.new(#888888, 40), style=line.style_dashed, width=1)'
            )
            lines.append(f'    if show_labels')
            lines.append(
                f'        label.new(anchor, {lvl}, "{lbl} {lvl}", '
                f'color=color.new(#888888, 40), textcolor=color.white, '
                f'style=label.style_label_left, size=size.tiny)'
            )
    for node in result.get("hvn_nodes", [])[:15]:
        ph, pl = node["price_high"], node["price_low"]
        vpct   = node["volume_pct"]
        is_poc = (pl <= poc <= ph) if poc else False
        col    = "c_vp_poc" if is_poc else "c_vp_hvn"
        lines.append(
            f'    box.new(anchor-{left}, {ph}, anchor+{future_bars}, {pl}, '
            f'bgcolor={col}, border_color=color.new(color.white, 100))'
        )
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor+{future_bars}+1, {round((ph+pl)/2, 2)}, '
            f'"HVN {vpct:.1f}%", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.tiny)'
        )
    for node in result.get("lvn_nodes", [])[:15]:
        ph, pl = node["price_high"], node["price_low"]
        vpct   = node["volume_pct"]
        lines.append(
            f'    box.new(anchor-{left}, {ph}, anchor+{future_bars}, {pl}, '
            f'bgcolor=c_vp_lvn, border_color=color.new(color.white, 100))'
        )
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor+{future_bars}+1, {round((ph+pl)/2, 2)}, '
            f'"LVN {vpct:.1f}%", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.tiny)'
        )
    return lines or _nothing("Volume profile: no levels")


# ── Market Structure ──────────────────────────────────────────────────────────

def _pine_market_structure(
    result: dict, df: pd.DataFrame, future_bars: int, swing_lookback: int = 5
) -> list[str]:
    """
    Draws EXACTLY what the rewritten detector computes (P0-3):
    confirmed library swings + close-break structure events from
    smc.bos_choch. No re-derived state machine — if the chart disagrees
    with the detector output, that IS the bug being looked for.

    B&W style:
      Swing highs  — c_structure triangle-down markers
      Swing lows   — c_block_active triangle-up markers
      Event line   — swing → break bar at the broken level (2px BOS, 1px cBOS)
      Bullish event label — c_structure (black), bearish — c_fvg_line (red)
      Last SwH/SwL lines — dotted
    """
    if result.get("status"):
        return _nothing(f"Market structure: {result['status']}")

    from copilot.detectors.smc_lib import confirmed_swings, lib_swings, structure_events

    shl    = lib_swings(df, swing_lookback)
    swings = confirmed_swings(shl, df)
    events = structure_events(df, shl)
    n      = len(df)
    lines: list[str] = []

    # ── 1. Confirmed swing markers (boundary synthetics excluded) ────────────
    for s in swings:
        age   = max(1, n - 1 - s["idx"])
        price = round(s["price"], 2)
        if s["type"] == "high":
            lines.append(
                f'    label.new(anchor-{age}, {price}, "H {price}", '
                f'color=c_structure, textcolor=color.white, '
                f'style=label.style_triangledown, size=size.tiny)'
            )
        else:
            lines.append(
                f'    label.new(anchor-{age}, {price}, "L {price}", '
                f'color=c_block_active, textcolor=color.white, '
                f'style=label.style_triangleup, size=size.tiny)'
            )

    # ── 2. Structure events: line from the swing to the break bar ────────────
    # Verify manually: the line must END at a candle whose CLOSE crossed the
    # level. A wick touching it must not produce an event.
    for i, ev in enumerate(events):
        age_swing = max(1, n - 1 - ev["swing_idx"])
        age_break = max(1, n - 1 - ev["break_idx"])
        level     = round(ev["level"], 2)
        width     = 2 if ev["type"] == "BOS" else 1
        color     = "c_structure" if ev["direction"] == "bullish" else "c_fvg_line"
        style     = ("label.style_label_up" if ev["direction"] == "bullish"
                     else "label.style_label_down")
        arrow     = "↑" if ev["direction"] == "bullish" else "↓"
        lines.append(
            f'    line.new(anchor-{age_swing}, {level}, anchor-{age_break}, {level}, '
            f'color={color}, style=line.style_solid, width={width})'
        )
        lines.append(
            f'    label.new(anchor-{age_break}, {level}, '
            f'"{ev["type"]}{arrow} #{i+1} @{level}", '
            f'color={color}, textcolor=color.white, style={style}, size=size.tiny)'
        )

    # ── 3. Last SwH / SwL dotted extension lines ──────────────────────────────
    sh = result.get("last_swing_high") or {}
    sl = result.get("last_swing_low")  or {}
    if sh.get("price") and sh.get("ts"):
        sh_age = max(1, _ts_to_age(df, sh["ts"]))
        sh_p   = sh["price"]
        lines += [
            f'    line.new(anchor-{sh_age}, {sh_p}, anchor+{future_bars}, {sh_p}, '
            f'color=c_structure, style=line.style_dotted, width=1)',
        ]
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor, {sh_p}, "SwH {sh_p}", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.tiny)'
        )
    if sl.get("price") and sl.get("ts"):
        sl_age = max(1, _ts_to_age(df, sl["ts"]))
        sl_p   = sl["price"]
        lines += [
            f'    line.new(anchor-{sl_age}, {sl_p}, anchor+{future_bars}, {sl_p}, '
            f'color=c_block_active, style=line.style_dotted, width=1)',
        ]
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor, {sl_p}, "SwL {sl_p}", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.tiny)'
        )

    # ── 4. Summary label ─────────────────────────────────────────────────────
    state         = result.get("state", "unknown")
    bars_in_state = result.get("bars_in_state", 0)
    current_price = result.get("current_price", 0)
    atr           = result.get("atr_14", 0)
    last_bos_type = result.get("last_bos_type") or "—"
    state_col     = (
        "c_structure"  if state == "bullish" else
        "c_fvg_line"   if state == "bearish" else
        "c_block_active"
    )
    lines.append(
        f'    label.new(anchor+1, {current_price}, '
        f'"MS: {state} ({last_bos_type}) | {bars_in_state} bars | ATR:{atr}", '
        f'color={state_col}, textcolor=color.white, '
        f'style=label.style_label_left, size=size.small)'
    )
    return lines or _nothing("No swing points detected")


# ── Fractals ──────────────────────────────────────────────────────────────────

def _pine_fractals(result: dict, future_bars: int) -> list[str]:
    """
    Swing highs: c_structure triangle-down (fresh) / c_block_active (swept).
    Swing lows:  c_block_active triangle-up (fresh) / c_block_mit (swept).
    Price shown in label.
    """
    lines = []
    for f in result.get("fractals", []):
        age   = max(1, int(f["age_bars"]))
        price = f["price"]
        ftype = f["type"]
        swept = f["is_swept"]
        if ftype == "swing_high":
            color = "c_block_active" if swept else "c_structure"
            style = "label.style_triangledown"
            txt   = f"H {price}"
        else:
            color = "c_block_mit" if swept else "c_block_active"
            style = "label.style_triangleup"
            txt   = f"L {price}"
        lines.append(
            f'    label.new(anchor-{age}, {price}, "{txt}", '
            f'color={color}, textcolor=color.white, style={style}, size=size.tiny)'
        )
    return lines or _nothing("No fractals detected")


# ── Fib Zones ─────────────────────────────────────────────────────────────────

def _pine_fib_zones(result: dict, bars: int, future_bars: int) -> list[str]:
    """
    Premium / Discount: c_block_active boxes.
    OTE (61.8–78.6%): c_fvg_fill (hot zone).
    EQ 50% line: c_structure dashed.
    Key fib levels: c_block_active dotted.
    """
    if result.get("status"):
        return _nothing(f"Fib zones: {result['status']}")
    lines = []
    left      = bars - 1
    pz        = result.get("premium_zone", {})
    dz        = result.get("discount_zone", {})
    ote       = result.get("ote", {})
    eq        = result.get("equilibrium")
    key       = result.get("key_levels", {})
    loc       = result.get("current_price_location", "")
    in_ote    = result.get("in_ote", False)
    cur       = result.get("current_price", 0)
    fib_ratio = result.get("current_fib_ratio", 0)

    if pz.get("upper") and pz.get("lower"):
        lines.append(
            f'    box.new(anchor-{left}, {pz["upper"]}, anchor+{future_bars}, {pz["lower"]}, '
            f'bgcolor=c_block_active, border_color=color.new(color.white, 100))'
        )
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor-{left}+1, {pz["upper"]}, "Premium", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.small)'
        )
    if dz.get("upper") and dz.get("lower"):
        lines.append(
            f'    box.new(anchor-{left}, {dz["upper"]}, anchor+{future_bars}, {dz["lower"]}, '
            f'bgcolor=c_block_active, border_color=color.new(color.white, 100))'
        )
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor-{left}+1, {dz["lower"]}, "Discount", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.small)'
        )
    if ote.get("upper") and ote.get("lower"):
        lines.append(
            f'    box.new(anchor-{left}, {ote["upper"]}, anchor+{future_bars}, {ote["lower"]}, '
            f'bgcolor=c_fvg_fill, border_color=c_fvg_line)'
        )
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor-{left}+1, {ote["upper"]}, "OTE 61.8-78.6%", '
            f'color=c_fvg_line, textcolor=color.white, '
            f'style=label.style_none, size=size.small)'
        )
    if eq:
        lines += [
            f'    line.new(anchor-{left}, {eq}, anchor+{future_bars}, {eq}, '
            f'color=c_structure, style=line.style_dashed, width=1)',
        ]
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor, {eq}, "EQ 50%", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.tiny)'
        )
    for fib_key in ("0.0", "0.236", "0.382", "0.618", "0.786", "1.0"):
        price = key.get(fib_key)
        if price:
            lines += [
                f'    line.new(anchor-{left}, {price}, anchor+{future_bars}, {price}, '
                f'color=c_block_active, style=line.style_dotted, width=1)',
            ]
            lines.append(f'    if show_labels')
            lines.append(
                f'        label.new(anchor-{left}, {price}, "{fib_key}", '
                f'color=color.new(color.white, 100), textcolor=color.black, '
                f'style=label.style_none, size=size.tiny)'
            )
    ote_tag = " IN OTE!" if in_ote else ""
    lines.append(
        f'    label.new(anchor, {cur}, "Loc: {loc}{ote_tag} | ratio: {fib_ratio:.3f}", '
        f'color=c_structure, textcolor=color.white, '
        f'style=label.style_label_left, size=size.small)'
    )
    return lines


# ── Compression ───────────────────────────────────────────────────────────────

def _pine_compression(result: dict, df: pd.DataFrame, future_bars: int) -> list[str]:
    """
    Active: c_fvg_fill (hot — price is coiling).
    Ended:  c_block_active (neutral).
    """
    if result.get("status"):
        return _nothing(f"Compression: {result['status']}")
    lines = []
    for c in result.get("compressions", []):
        age_end   = max(1, c["bars_since_end"])
        age_start = age_end + c["bars"] - 1
        ph, pl    = _compression_bounds(df, c["start_ts"], c["end_ts"])
        if ph is None:
            continue
        is_active = c["is_active"]
        bg        = "c_fvg_fill"     if is_active else "c_block_active"
        bc        = "c_fvg_line"     if is_active else "color.new(color.white, 100)"
        txt = (f"COMP {'ACTIVE' if is_active else 'ended'} "
               f"{c['bars']}b sq:{c['squeeze_ratio']}x "
               f"tAtr:{c['tightest_range_atr']}")
        lines.append(
            f'    box.new(anchor-{age_start}, {ph}, anchor-{age_end}, {pl}, '
            f'bgcolor={bg}, border_color={bc})'
        )
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor-{age_start}+1, {ph}, "{txt}", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.tiny)'
        )
    return lines or _nothing("No compressions detected")


def _compression_bounds(df: pd.DataFrame, start_ts: str, end_ts: str) -> tuple[float | None, float | None]:
    """Get the actual high/low of the price range during a compression window."""
    try:
        s = pd.Timestamp(start_ts, tz="UTC") if "+" not in start_ts and "Z" not in start_ts \
            else pd.Timestamp(start_ts)
        e = pd.Timestamp(end_ts,   tz="UTC") if "+" not in end_ts   and "Z" not in end_ts \
            else pd.Timestamp(end_ts)
        if s.tzinfo is None:
            s = s.tz_localize("UTC")
        if e.tzinfo is None:
            e = e.tz_localize("UTC")
        mask = (df.index >= s) & (df.index <= e)
        if not mask.any():
            return None, None
        return float(df.loc[mask, "high"].max()), float(df.loc[mask, "low"].min())
    except Exception:
        return None, None


# ── Sponsored Candle ──────────────────────────────────────────────────────────

def _pine_sponsored_candle(result: dict, future_bars: int) -> list[str]:
    """
    High-quality OB — same block style as OB: c_block_active / c_block_mit.
    Sweep side shown in label.
    """
    if result.get("status"):
        return _nothing(f"Sponsored candle: {result['status']}")
    lines = []
    for z in result.get("candles", []):
        age      = max(1, int(z["age_bars"]))
        top, bot = z["high"], z["low"]
        ztype    = z["ob_type"]
        mit      = z.get("is_mitigated", False)
        sw_side  = z.get("sweep_side", "?")[:3]
        arrow    = "↑" if ztype == "bullish" else "↓"
        label    = f"SpC{arrow} sw:{sw_side}"
        if mit:
            lines.append(
                f'    box.new(anchor-{age}, {top}, anchor, {bot}, '
                f'bgcolor=c_block_mit, border_color=color.new(color.white, 100))'
            )
            lines.append(f'    if show_labels')
            lines.append(
                f'        label.new(anchor-{age}+1, {top}, "{label} mit", '
                f'color=color.new(color.white, 100), textcolor=color.black, '
                f'style=label.style_none, size=size.tiny)'
            )
        else:
            lines.append(
                f'    box.new(anchor-{age}, {top}, anchor+{future_bars}, {bot}, '
                f'bgcolor=c_block_active, border_color=color.new(color.white, 100))'
            )
            lines.append(f'    if show_labels')
            lines.append(
                f'        label.new(anchor-{age}+1, {top}, "{label}", '
                f'color=color.new(color.white, 100), textcolor=color.black, '
                f'style=label.style_none, size=size.tiny)'
            )
    return lines or _nothing("No sponsored candles detected")


# ── Absorption at POI ─────────────────────────────────────────────────────────

def _pine_absorption_poi(result: dict, future_bars: int) -> list[str]:
    """
    Absorbed: c_fvg_fill with c_fvg_line border (hot = trade setup).
    Not absorbed: c_block_active (neutral).
    Debug metrics shown in side label.
    """
    poi_zone = result.get("poi_zone")
    poi_type = result.get("poi_type", "none")
    reversal = result.get("reversal_direction", "none")
    absorbed = result.get("absorption_detected", False)
    poi_hit  = result.get("poi_hit", False)
    if not poi_zone or poi_type == "none":
        return _nothing(f"No POI absorption — poi_type:{poi_type} hit:{poi_hit}")
    ph = poi_zone["high"]
    pl = poi_zone["low"]
    bg = "c_fvg_fill"   if absorbed else "c_block_active"
    bc = "c_fvg_line"   if absorbed else "color.new(color.white, 100)"
    txt = f"Abs:{'YES' if absorbed else 'no'} | {poi_type} | rev:{reversal}"
    lines = [
        f'    box.new(anchor-5, {ph}, anchor+{future_bars}, {pl}, '
        f'bgcolor={bg}, border_color={bc})',
    ]
    lines.append(f'    if show_labels')
    lines.append(
        f'        label.new(anchor+{future_bars}+1, {round((ph+pl)/2, 2)}, "{txt}", '
        f'color=color.new(color.white, 100), textcolor=color.black, '
        f'style=label.style_none, size=size.small)'
    )
    detail = result.get("absorption_detail", {})
    if detail:
        vr = detail.get("vol_ratio", 0)
        cp = detail.get("close_position", 0)
        ar = detail.get("range_atr_ratio", 0)
        lines.append(f'    if show_labels')
        lines.append(
            f'        label.new(anchor+{future_bars}+1, {pl}, '
            f'"vol:{vr:.2f} cls:{cp:.2f} atr:{ar:.2f}", '
            f'color=color.new(color.white, 100), textcolor=color.black, '
            f'style=label.style_none, size=size.tiny)'
        )
    return lines


# ── Cumulative Delta ──────────────────────────────────────────────────────────

def _pine_cumulative_delta(result: dict, df: pd.DataFrame, future_bars: int) -> list[str]:
    """
    Session delta trend label: c_fvg_line if negative (warning), c_structure if positive.
    CD divergence markers: c_fvg_line triangles (divergence = alert regardless of direction).
    """
    if result.get("status"):
        return _nothing(f"Cumulative delta: {result['status']}")
    lines = []
    trend = result.get("delta_trend", "neutral")
    delta = result.get("session_delta", 0)
    # Negative delta (selling pressure) = c_fvg_line, positive = c_structure
    tc = "c_fvg_line" if trend == "negative" else ("c_structure" if trend == "positive" else "c_block_active")
    lines.append(
        f'    label.new(anchor+1, close, "CD session:{delta:.1f} trend:{trend}", '
        f'color={tc}, textcolor=color.white, style=label.style_label_left, size=size.small)'
    )
    for div in result.get("divergences", []):
        dtype  = div["type"]
        bar_ts = div.get("bar_ts")
        price  = div.get("price_high") or div.get("price_low") or 0
        if not (price and bar_ts):
            continue
        age   = _ts_to_age(df, bar_ts)
        # Both divergence types = c_fvg_line (red = disagreement between price and delta)
        # P0-5 semantics to verify: the marker must sit on the window's price
        # extreme (confirmed, never the live bar), with CD already declining
        # (bearish) / rising (bullish) into it.
        style = "label.style_triangledown" if dtype == "bearish" else "label.style_triangleup"
        lines.append(
            f'    label.new(anchor-{age}, {price}, "CD div {dtype}", '
            f'color=c_fvg_line, textcolor=color.white, style={style}, size=size.small)'
        )

    # P0-5 sweep confirmation — pool-anchored, close-back. Verify: the marked
    # bar must WICK beyond a liquidity pool and close back inside; a bar that
    # closed through the level must never carry this marker.
    sweep = result.get("sweep_confirmation")
    if sweep and sweep.get("last_sweep_ts"):
        age   = _ts_to_age(df, sweep["last_sweep_ts"])
        side  = sweep.get("sweep_side", "?")
        manip = sweep.get("confirmed_manipulation", False)
        cd_at = sweep.get("cd_at_sweep", 0)
        col   = "c_fvg_line" if manip else "c_block_active"
        lines.append(
            f'    label.new(anchor-{age}, high[{age}], '
            f'"SWEEP {side} | delta:{cd_at:+.1f} | manip:{"YES" if manip else "no"}", '
            f'color={col}, textcolor=color.white, '
            f'style=label.style_label_down, size=size.small)'
        )

    if len(lines) == 1:
        lines.append(_nothing("No CD divergences / sweeps")[0])
    return lines


# ── CD Divergence at Structure ────────────────────────────────────────────────

def _pine_cd_divergence(result: dict, df: pd.DataFrame, future_bars: int) -> list[str]:
    """
    Detected: c_fvg_line for bearish div (red = alert), c_structure for bullish.
    Sweep marker: c_fvg_line label_up.
    """
    if result.get("reason"):
        return _nothing(f"CDdiv: {result['reason']}")
    detected    = result.get("divergence_detected", False)
    dtype       = result.get("type", "none")
    at_struct   = result.get("at_structure", False)
    level       = result.get("structure_level")
    struct_type = result.get("structure_type", "")
    strength    = result.get("signal_strength", "none")
    sweep_prec  = result.get("sweep_preceded", False)
    sweep_ts    = result.get("sweep_ts")
    if not (detected and level):
        return _nothing(
            f"No CD div | type:{dtype} at_struct:{at_struct} strength:{strength}"
        )
    # Bearish divergence = c_fvg_line (red), bullish = c_structure (black)
    lc  = "c_fvg_line" if dtype == "bearish" else "c_structure"
    txt = f"CD {dtype} @ {struct_type} | {strength}{'  swept' if sweep_prec else ''}"
    lines = [
        f'    line.new(0, {level}, anchor+{future_bars}, {level}, '
        f'color={lc}, style=line.style_dashed, width=2)',
    ]
    lines.append(f'    if show_labels')
    lines.append(
        f'        label.new(anchor, {level}, "{txt}", '
        f'color={lc}, textcolor=color.white, '
        f'style=label.style_label_left, size=size.small)'
    )
    if sweep_prec and sweep_ts:
        age = _ts_to_age(df, sweep_ts)
        lines.append(
            f'    label.new(anchor-{age}, {level}, "✕ SWEEP", '
            f'color=c_fvg_line, textcolor=color.white, '
            f'style=label.style_label_up, size=size.tiny)'
        )
    return lines


# ── Killzone ──────────────────────────────────────────────────────────────────

def _pine_killzone(result: dict) -> list[str]:
    """
    Session state table (top-right).
    Active killzone / OTT: c_fvg_line (red highlight).
    Inactive / neutral: c_block_active.
    Friday: c_structure (black = caution).
    """
    kz      = result.get("active_killzone") or "none"
    next_kz = result.get("next_killzone") or "—"
    t_str   = result.get("kyiv_time", "")
    weekday = result.get("weekday", "")
    ott     = result.get("in_ott_window", False)
    is_fri  = result.get("is_friday", False)
    kz_c    = "c_fvg_line"     if kz != "none" else "c_block_active"
    ott_c   = "c_fvg_line"     if ott          else "c_block_active"
    fri_c   = "c_structure"    if is_fri       else "c_block_active"
    return [
        f'    var _kzt = table.new(position.top_right, 2, 5, '
        f'bgcolor=color.new(color.white, 10), frame_color=c_block_active, frame_width=1)',
        f'    table.cell(_kzt, 0, 0, "Killzone",  text_color=c_block_active, text_size=size.small)',
        f'    table.cell(_kzt, 1, 0, "{kz}",       text_color={kz_c}, text_size=size.small)',
        f'    table.cell(_kzt, 0, 1, "Kyiv time",  text_color=c_block_active, text_size=size.small)',
        f'    table.cell(_kzt, 1, 1, "{t_str} {weekday}", text_color=c_structure, text_size=size.small)',
        f'    table.cell(_kzt, 0, 2, "OTT window", text_color=c_block_active, text_size=size.small)',
        f'    table.cell(_kzt, 1, 2, "{"YES" if ott else "no"}", text_color={ott_c}, text_size=size.small)',
        f'    table.cell(_kzt, 0, 3, "Next KZ",    text_color=c_block_active, text_size=size.small)',
        f'    table.cell(_kzt, 1, 3, "{next_kz}",  text_color=c_structure, text_size=size.small)',
        f'    table.cell(_kzt, 0, 4, "Friday",     text_color=c_block_active, text_size=size.small)',
        f'    table.cell(_kzt, 1, 4, "{"YES" if is_fri else "no"}", text_color={fri_c}, text_size=size.small)',
    ]


# ── Multi-TF Alignment ────────────────────────────────────────────────────────

def _pine_multi_tf(result: dict, htf: str, ltf: str) -> list[str]:
    """
    MTF alignment table (top-left).
    Aligned / bullish bias = c_structure (black = clear/positive).
    Not aligned / bearish = c_fvg_line (red = conflict/alert).
    desync = c_fvg_line.
    """
    aligned = result.get("aligned", False)
    bias    = result.get("htf_bias", "unknown")
    role    = result.get("ltf_role", "unknown")
    sync    = result.get("sync_quality", "unknown")
    al_c    = "c_structure"   if aligned             else "c_fvg_line"
    bias_c  = "c_structure"   if bias == "bullish"   else ("c_fvg_line" if bias == "bearish" else "c_block_active")
    sync_c  = {"strong": "c_structure", "weak": "c_block_active", "desync": "c_fvg_line"}.get(sync, "c_block_active")
    return [
        f'    var _mtft = table.new(position.top_left, 2, 4, '
        f'bgcolor=color.new(color.white, 10), frame_color=c_block_active, frame_width=1)',
        f'    table.cell(_mtft, 0, 0, "MTF Align ({htf}/{ltf})", text_color=c_block_active, text_size=size.small)',
        f'    table.cell(_mtft, 1, 0, "{"YES" if aligned else "NO"}", text_color={al_c}, text_size=size.small)',
        f'    table.cell(_mtft, 0, 1, "HTF bias ({htf})",          text_color=c_block_active, text_size=size.small)',
        f'    table.cell(_mtft, 1, 1, "{bias}",                    text_color={bias_c}, text_size=size.small)',
        f'    table.cell(_mtft, 0, 2, "LTF role ({ltf})",          text_color=c_block_active, text_size=size.small)',
        f'    table.cell(_mtft, 1, 2, "{role}",                    text_color=c_structure, text_size=size.small)',
        f'    table.cell(_mtft, 0, 3, "Sync quality",              text_color=c_block_active, text_size=size.small)',
        f'    table.cell(_mtft, 1, 3, "{sync}",                    text_color={sync_c}, text_size=size.small)',
    ]


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run detectors on BTCUSDT spot and write one Pine Script file per detector.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--symbol",   default="BTCUSDT", help="Trading pair (default: BTCUSDT)")
    parser.add_argument("--tf",       default="30m",
                        choices=sorted(VALID_TIMEFRAMES),
                        help="Timeframe (default: 30m)")
    parser.add_argument("--bars",     default=500, type=int, help="Number of bars (default: 500)")
    parser.add_argument("--future",   default=50,  type=int, help="Future bars to extend zones (default: 50)")
    parser.add_argument("--out",      default="./pine_debug", help="Output directory (default: ./pine_debug)")
    parser.add_argument("--detector", default=None, metavar="NAME",
                        help="Run only this detector (default: run all).\nSee available names with --list.")
    parser.add_argument("--swing-lookback", default=None, type=int, metavar="N",
                        help="Swing pivot sensitivity for market_structure / bos /\n"
                             "order_block / liquidity (default: each detector's own default).")
    parser.add_argument("--list",     action="store_true",
                        help="Print all detector names with their June-2026 audit status and exit.")
    args = parser.parse_args()

    if args.list:
        print("Available detectors (status per June 2026 audit / P0 rewrites):")
        width = max(len(n) for n in _ALL_DETECTOR_NAMES) + 2
        for name in _ALL_DETECTOR_NAMES:
            print(f"  {name:<{width}}{_DETECTOR_STATUS.get(name, '')}")
        return

    selected: str | None = args.detector
    if selected is not None and selected not in _ALL_DETECTOR_NAMES:
        print(f"error: unknown detector '{selected}'")
        print(f"Available: {', '.join(_ALL_DETECTOR_NAMES)}")
        sys.exit(1)

    active_names: frozenset[str] = (
        frozenset({selected}) if selected else frozenset(_ALL_DETECTOR_NAMES)
    )

    symbol      = args.symbol.upper()
    tf          = args.tf
    bars        = args.bars
    future_bars = args.future
    out_dir     = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Swing sensitivity: explicit flag overrides; otherwise each detector's
    # own default is used (5 for ms/bos/ob, 3 for liquidity) so the debug
    # output matches what the MCP tools return.
    ms_lookback = args.swing_lookback or 5
    sl_kwargs: dict = (
        {"swing_lookback": args.swing_lookback} if args.swing_lookback else {}
    )

    htf = _HTF_MAP.get(tf, "4h")

    print(f"Fetching {symbol} spot — {tf} × {bars} bars …")
    source = BinanceSource(market="spot")
    df = source.get_ohlc(symbol, tf, bars)
    print(f"  OK — {len(df)} bars  {df.index[0]}  →  {df.index[-1]}")

    df_delta = df
    if active_names & _NEEDS_DELTA:
        print(f"Fetching delta data ({tf}) …")
        try:
            df_delta = fetch_ohlcv_with_delta(symbol, tf, bars, market="spot")
            print(f"  OK — delta columns: {list(df_delta.columns)}")
        except Exception as exc:
            print(f"  WARNING: delta fetch failed ({exc}). CD detectors will show error label.")

    htf_ms_result: dict = {}
    ltf_ms_result: dict = {}
    if active_names & (_NEEDS_HTF | _NEEDS_MS):
        ltf_ms_result = detect_market_structure(df)
    if active_names & _NEEDS_HTF and htf != tf:
        print(f"Fetching HTF data ({htf}) for multi-TF alignment …")
        try:
            df_htf = source.get_ohlc(symbol, htf, 200)
            htf_ms_result = detect_market_structure(df_htf)
        except Exception as exc:
            print(f"  WARNING: HTF fetch failed ({exc}).")
            htf_ms_result = ltf_ms_result
    elif active_names & _NEEDS_HTF:
        htf_ms_result = ltf_ms_result

    # ── Build task list ───────────────────────────────────────────────────────
    tasks = [
        ("detect_fvg",
            lambda: detect_fvg(df),
            lambda r: _pine_fvg(r, future_bars)),

        ("detect_order_block",
            lambda: detect_order_block(df, **sl_kwargs),
            lambda r: _pine_order_block(r, future_bars)),

        ("detect_ifvg",
            lambda: detect_ifvg(df),
            lambda r: _pine_ifvg(r, future_bars)),

        ("detect_breaker_block",
            lambda: detect_breaker_block(df, lookback=bars, max_results=20, **sl_kwargs),
            lambda r: _pine_breaker_block(r, future_bars)),

        ("detect_rejection_block",
            lambda: detect_rejection_block(df),
            lambda r: _pine_rejection_block(r, future_bars)),

        ("detect_mitigation_block",
            lambda: detect_mitigation_block(df, lookback=bars, max_results=20, **sl_kwargs),
            lambda r: _pine_mitigation_block(r, future_bars)),

        ("detect_liquidity",
            lambda: detect_liquidity(df, **sl_kwargs),
            lambda r: _pine_liquidity(r, df, future_bars)),

        ("detect_bos",
            lambda: detect_bos(df, max_results=30, **sl_kwargs),
            lambda r: _pine_bos(r, df, future_bars, ms_lookback)),

        ("detect_volume_profile",
            lambda: detect_volume_profile(df),
            lambda r: _pine_volume_profile(r, bars, future_bars)),

        ("detect_market_structure",
            lambda: detect_market_structure(df, **sl_kwargs),
            lambda r: _pine_market_structure(r, df, future_bars, ms_lookback)),

        ("detect_fractals",
            lambda: detect_fractals(df),
            lambda r: _pine_fractals(r, future_bars)),

        ("detect_fib_zones",
            lambda: detect_fib_zones(
                df,
                swing_high=ltf_ms_result.get("last_swing_high", {}).get("price") or float(df["high"].max()),
                swing_low =ltf_ms_result.get("last_swing_low",  {}).get("price") or float(df["low"].min()),
            ),
            lambda r: _pine_fib_zones(r, bars, future_bars)),

        ("detect_compression",
            lambda: detect_compression(df),
            lambda r: _pine_compression(r, df, future_bars)),

        ("detect_sponsored_candle",
            lambda: detect_sponsored_candle(df, lookback=bars, max_results=20, **sl_kwargs),
            lambda r: _pine_sponsored_candle(r, future_bars)),

        ("check_absorption_at_poi",
            lambda: check_absorption_at_poi(df),
            lambda r: _pine_absorption_poi(r, future_bars)),

        ("detect_cumulative_delta",
            lambda: detect_cumulative_delta(df_delta),
            lambda r: _pine_cumulative_delta(r, df, future_bars)),

        ("check_cd_divergence_at_structure",
            lambda: check_cd_divergence_at_structure(df_delta),
            lambda r: _pine_cd_divergence(r, df, future_bars)),

        ("current_killzone",
            lambda: current_killzone(),
            lambda r: _pine_killzone(r)),

        ("check_multi_tf_alignment",
            lambda: check_multi_tf_alignment(
                htf_state=htf_ms_result.get("state", "ranging"),
                ltf_state=ltf_ms_result.get("state", "ranging"),
                htf_timeframe=htf,
                ltf_timeframe=tf,
            ),
            lambda r: _pine_multi_tf(r, htf, tf)),
    ]

    tasks = [t for t in tasks if t[0] in active_names]

    print(f"\nRunning {len(tasks)} detector{'s' if len(tasks) != 1 else ''} …")
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(run_fn): name for name, run_fn, _ in tasks}
        for fut in futures:
            name = futures[fut]
            try:
                results[name] = fut.result(timeout=30)
            except Exception as exc:
                print(f"  ERROR  {name}: {exc}")
                results[name] = {"status": "error", "error": str(exc)}

    saved = 0
    errors = 0
    print()
    for name, run_fn, pine_fn in tasks:
        result = results.get(name, {})
        try:
            body  = pine_fn(result)
            hdr   = _header(symbol, tf, name, future_bars)
            pine  = _assemble(hdr, body)
            fname = f"{name}_{symbol}_{tf}.pine"
            (out_dir / fname).write_text(pine, encoding="utf-8")
            # Raw detector output — cross-check every drawn level against it
            jname = f"{name}_{symbol}_{tf}.json"
            (out_dir / jname).write_text(
                json.dumps(result, default=str, indent=2), encoding="utf-8"
            )
            status = result.get("status", "ok")
            count_key = next(
                (k for k in ("count_active", "count", "compressions") if k in result), None
            )
            count_str = f" ({result[count_key]} zones)" if count_key and isinstance(result.get(count_key), int) else ""
            q_tag = "  ⚠ QUARANTINED — output known-bad" if name in _QUARANTINED else ""
            print(f"  OK     {fname}  [{status}{count_str}]{q_tag}")
            saved += 1
        except Exception as exc:
            print(f"  ERROR  {name}: {exc}")
            errors += 1

    print(f"\n{'─'*60}")
    print(f"Saved {saved} Pine Script files (+ raw .json each) → {out_dir.resolve()}")
    if errors:
        print(f"Errors: {errors}")
    print(
        "\nHow to verify a detector:"
        "\n  1. Open TradingView and switch the chart to "
        f"{symbol} {tf}"
        "\n  2. Pine Script Editor → New indicator → paste the .pine content → Save"
        "\n  3. 'Add to chart' — zones appear anchored to the last bar"
        "\n  4. Cross-check each drawn level against the .json raw output"
        "\n  5. Check the verification hint per detector: --list shows what to look for"
        "\n\nRewritten detectors to re-verify first (P0-3/P0-5):"
        "\n  detect_market_structure  — state flips ONLY on a candle CLOSE through a level"
        "\n  detect_bos               — every event line ends at a close-break candle"
        "\n  detect_order_block       — OB candle = deepest retracement before the break"
        "\n  detect_liquidity         — sweeps: wick beyond pool + close back; breaks excluded"
        "\n  detect_cumulative_delta  — divergence at confirmed extreme; sweep is pool-anchored"
    )


if __name__ == "__main__":
    main()
