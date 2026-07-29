"""
Multi-timeframe alignment checker.

Takes the MS state results from two timeframes (HTF and LTF) and determines:
- Whether they are directionally aligned
- What role the LTF plays in HTF context (pullback = RTO, continuation, counter-trend)
- Sync quality: strong / weak / desync

Per KB: in HTF uptrend, LTF downward correction = RTO (Reverse Trade Opportunity),
not a context break. Only trade LTF in RTO direction when htf_sync = True.
"""

TOOL_SCHEMA = {
    "name": "check_multi_tf_alignment",
    "description": (
        "Reconcile market structure states across two timeframes. "
        "Determines if LTF is in a pullback (RTO), continuation, or counter-trend move "
        "relative to HTF bias. Use after calling detect_market_structure on both timeframes "
        "to confirm setup quality. Strong sync = higher probability setup."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "htf_state": {
                "type": "string",
                "enum": ["bullish", "bearish", "ranging"],
                "description": "Market structure state on the higher timeframe",
            },
            "ltf_state": {
                "type": "string",
                "enum": ["bullish", "bearish", "ranging"],
                "description": "Market structure state on the lower timeframe",
            },
            "htf_timeframe": {
                "type": "string",
                "description": "e.g. '4h' (for context in the report)",
            },
            "ltf_timeframe": {
                "type": "string",
                "description": "e.g. '15m'",
            },
        },
        "required": ["htf_state", "ltf_state"],
    },
}


def check_multi_tf_alignment(
    htf_state: str,
    ltf_state: str,
    htf_timeframe: str = "",
    ltf_timeframe: str = "",
) -> dict:
    """Pure function: no DataFrame needed — works on state strings."""

    if htf_state == "ranging":
        return {
            "aligned": False,
            "htf_bias": htf_state,
            "ltf_role": "unclear",
            "sync_quality": "desync",
            "htf_timeframe": htf_timeframe,
            "ltf_timeframe": ltf_timeframe,
            "note": "HTF is ranging — no directional bias to align with.",
        }

    # HTF is trending. One classification covers every LTF state coherently:
    #   ltf == htf        → continuation (strong sync)
    #   ltf == opposite   → pullback / RTO against the trend (strong sync)
    #   ltf == ranging    → consolidating inside the trend (weak sync, but coherent)
    opposite = {"bullish": "bearish", "bearish": "bullish"}
    if ltf_state == htf_state:
        ltf_role, quality, aligned = "continuation", "strong", True
    elif ltf_state == opposite[htf_state]:
        # The key SMC setup: LTF correction against HTF bias; expect LTF to
        # reverse and rejoin the HTF trend.
        ltf_role, quality, aligned = "pullback", "strong", True
    else:  # ltf_state == "ranging"
        ltf_role, quality, aligned = "consolidation", "weak", True

    note = _build_note(htf_state, ltf_state, ltf_role, htf_timeframe, ltf_timeframe)

    return {
        "aligned": aligned,
        "htf_bias": htf_state,
        "ltf_role": ltf_role,
        "sync_quality": quality,
        "htf_timeframe": htf_timeframe,
        "ltf_timeframe": ltf_timeframe,
        "note": note,
    }


def _build_note(htf: str, ltf: str, role: str, htf_tf: str, ltf_tf: str) -> str:
    if role == "pullback":
        return (
            f"{ltf_tf or 'LTF'} is pulling back ({ltf}) against {htf_tf or 'HTF'} trend ({htf}). "
            f"Look for {ltf_tf or 'LTF'} reversal signal (BOS + FVG/OB) to enter with HTF bias."
        )
    if role == "continuation":
        return (
            f"Both {htf_tf or 'HTF'} and {ltf_tf or 'LTF'} are {htf}. "
            f"Trend continuation mode — look for pullback entry on LTF before adding."
        )
    if role == "consolidation":
        return (
            f"{ltf_tf or 'LTF'} is ranging inside the {htf_tf or 'HTF'} {htf} trend. "
            f"Wait for an LTF break in the {htf} direction (BOS + FVG/OB) before entering."
        )
    return "Ambiguous alignment — wait for clearer structure on LTF."
