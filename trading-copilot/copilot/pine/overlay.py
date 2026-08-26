"""
Merged Pine Script v5 overlay — one indicator carrying several detector layers.

Differs from the per-detector debug files (`emitters.file_header`) in one
structural way: `anchor` is declared at **global** scope instead of inside
`if barstate.islast`. That lets each layer live in its own guarded block —

    if barstate.islast and show_fvg
        <emitter body, unchanged>

— so the emitter bodies (4-space indented, referencing `anchor`) drop in
verbatim, and the trader can toggle individual layers from the chart's settings
panel instead of editing the script.

Every emitter draws with box/line/label/table only, all of which are legal
inside an `if` block; nothing here emits top-level-only constructs (`plot`,
`alertcondition`, `hline`).
"""

from __future__ import annotations

from copilot.pine.emitters import EmitContext, emit, now_str

# Layers offered in the merged overlay, in draw order (structure first, so
# zones land on top of it).
#
# Deliberately excluded:
#   * every name in llm/tools.py `_QUARANTINED_TOOLS` — the LLM cannot see
#     those detectors, so it must not be able to chart them either
#     (tests/test_pine_overlay.py asserts the two sets stay disjoint);
#   * detect_cumulative_delta — needs buy_vol/sell_vol/delta columns, which the
#     registry does not fetch for this tool;
#   * current_killzone / check_multi_tf_alignment — their emitters draw info
#     tables, not price zones. Both remain available in the debug CLI.
OVERLAY_LAYERS: list[str] = [
    "detect_market_structure",
    "detect_bos",
    "detect_liquidity",
    "detect_fvg",
    "detect_ifvg",
    "detect_order_block",
    "detect_breaker_block",
    "detect_mitigation_block",
    "detect_sponsored_candle",
    "detect_volume_profile",
    "detect_fractals",
    "detect_fib_zones",
]

# Short toggle names + chart-panel labels. Keeping the toggle short matters:
# it is what the trader sees in the indicator settings.
_LAYER_UI: dict[str, tuple[str, str]] = {
    "detect_market_structure":  ("show_ms",       "Market structure"),
    "detect_bos":               ("show_bos",      "BOS / cBOS"),
    "detect_liquidity":         ("show_liq",      "Liquidity"),
    "detect_fvg":               ("show_fvg",      "FVG"),
    "detect_ifvg":              ("show_ifvg",     "IFVG"),
    "detect_order_block":       ("show_ob",       "Order blocks"),
    "detect_breaker_block":     ("show_brk",      "Breaker blocks"),
    "detect_mitigation_block":  ("show_mb",       "Mitigation blocks"),
    "detect_sponsored_candle":  ("show_sc",       "Sponsored candles"),
    "detect_volume_profile":    ("show_vp",       "Volume profile"),
    "detect_fractals":          ("show_fractals", "Fractals"),
    "detect_fib_zones":         ("show_fib",      "Fib / OTE"),
}

# Where a layer's "how many objects did this draw" number comes from. Missing
# keys fall back to counting the emitted drawing calls.
_COUNT_KEYS: tuple[str, ...] = ("count_active", "count")


def layer_toggle(detector: str) -> str:
    """Pine variable name gating *detector*'s block."""
    return _LAYER_UI[detector][0]


def _alerts_for(detector: str, result: dict) -> list[str]:
    """`alertcondition()` calls for a layer, or none.

    Carried over from the pre-Aug-2026 generator, which fired alerts on pool
    sweeps, zone entries and value-area crosses. They must sit at top level —
    Pine rejects alertcondition inside an `if` — so they are emitted separately
    from the layer bodies rather than by the emitters.
    """
    lines: list[str] = []

    if detector == "detect_liquidity":
        for pool in (result.get("buyside_liquidity") or [])[:5]:
            level = pool.get("price")
            if level is not None:
                lines.append(
                    f'alertcondition(ta.crossover(high, {level}), "BSL Sweep {level}", '
                    f'"Price swept BSL at {level}")'
                )
        for pool in (result.get("sellside_liquidity") or [])[:5]:
            level = pool.get("price")
            if level is not None:
                lines.append(
                    f'alertcondition(ta.crossunder(low, {level}), "SSL Sweep {level}", '
                    f'"Price swept SSL at {level}")'
                )

    elif detector == "detect_fvg":
        for zone in result.get("fvgs") or []:
            if zone.get("fill_state", "untouched") != "untouched":
                continue
            top, bot, ztype = zone.get("upper"), zone.get("lower"), zone.get("type", "")
            if top is None or bot is None:
                continue
            arrow = "↑" if ztype == "bullish" else "↓"
            lines.append(
                f'alertcondition(close >= {bot} and close <= {top}, "FVG{arrow} Entry {bot}", '
                f'"Price entered {ztype} FVG {bot}-{top}")'
            )

    elif detector == "detect_order_block":
        for ob in result.get("obs") or []:
            if ob.get("is_mitigated"):
                continue
            top, bot, ztype = ob.get("high"), ob.get("low"), ob.get("type", "")
            if top is None or bot is None:
                continue
            arrow = "↑" if ztype == "bullish" else "↓"
            lines.append(
                f'alertcondition(close >= {bot} and close <= {top}, "OB{arrow} Touch {bot}", '
                f'"Price touched {ztype} OB {bot}-{top}")'
            )

    elif detector == "detect_volume_profile":
        for label, level in (
            ("POC", result.get("poc")),
            ("VAH", result.get("vah")),
            ("VAL", result.get("val")),
        ):
            if level:
                lines.append(
                    f'alertcondition(ta.cross(close, {level}), "{label} Cross {level}", '
                    f'"Price crossed {label} at {level}")'
                )

    return lines


def _count_for(detector: str, result: dict, body: list[str]) -> int:
    for key in _COUNT_KEYS:
        value = result.get(key)
        if isinstance(value, int):
            return value
    return sum(1 for line in body if "box.new(" in line or "line.new(" in line)


def build_overlay(
    symbol: str,
    tf: str,
    layers: list[str],
    results: dict[str, dict],
    ctx: EmitContext,
) -> tuple[str, dict[str, int]]:
    """Assemble the merged indicator.

    Returns `(pine_script, per-layer object counts)`. `layers` is expected to be
    pre-validated against OVERLAY_LAYERS by the caller; unknown names raise.
    """
    ordered = [d for d in OVERLAY_LAYERS if d in layers]

    lines: list[str] = [
        f"// Generated by Trading Co-Pilot — {symbol} {tf} — {now_str()}",
        f"// Layers: {', '.join(ordered) or '(none)'}",
        "//@version=5",
        f'indicator("Co-Pilot: {symbol} {tf}", overlay=true, '
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
        "",
        "// ── Script parameters ─────────────────────────────────────────────────────────",
        'show_labels    = input.bool(true, "Show labels")',
        'drop_forming   = input.bool(true, "Source data drops the forming bar (shift anchor left 1)")',
    ]

    for detector in ordered:
        toggle, title = _LAYER_UI[detector]
        lines.append(f'{toggle:<14} = input.bool(true, "{title}", group="Layers")')

    lines += [
        "",
        # Declared globally (unlike the per-detector debug files, where it sits
        # inside the single `if barstate.islast`) so every layer block below can
        # reference it. The detector data excludes the forming candle while
        # barstate.islast fires ON the forming bar — without the shift the whole
        # overlay lands one bar to the right.
        "anchor = bar_index - (drop_forming ? 1 : 0)",
    ]

    alerts: list[str] = []
    for detector in ordered:
        alerts += _alerts_for(detector, results.get(detector, {}))
    if alerts:
        lines += [
            "",
            "// ── Alert conditions (top level — Pine forbids them inside `if`) ────────────",
            *alerts,
        ]

    counts: dict[str, int] = {}
    for detector in ordered:
        body = emit(detector, results.get(detector, {}), ctx)
        counts[detector] = _count_for(detector, results.get(detector, {}), body)
        lines += [
            "",
            f"// ── {_LAYER_UI[detector][1]} ({detector}) ─────────────────────────────",
            f"if barstate.islast and {_LAYER_UI[detector][0]}",
            *body,
        ]

    total = sum(counts.values())
    lines += [
        "",
        f"// ── Summary: {total} objects across {len(ordered)} layer(s) ──────────────",
        *[f"// {name}: {n}" for name, n in counts.items()],
    ]

    return "\n".join(lines), counts
