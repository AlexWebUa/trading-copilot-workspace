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
            "note": "HTF is ranging — no directional bias to align with.",
        }

    if ltf_state == htf_state:
        # Both point the same direction: continuation / trending day
        role = "continuation"
        quality = "strong"
    elif ltf_state == "ranging":
        # LTF is consolidating inside HTF trend: pullback accumulating
        role = "pullback"
        quality = "weak"
    else:
        # LTF runs opposite to HTF: RTO (Reverse Trade Opportunity on correction)
        role = "pullback"
        quality = "strong"  # Per KB: clear counter-LTF move = clean RTO

    opposite = {"bullish": "bearish", "bearish": "bullish"}
    if ltf_state == opposite.get(htf_state):
        # This is the key SMC setup: LTF correction against HTF bias
        ltf_role = "pullback"  # expect LTF to reverse and align with HTF
        aligned = True
    elif ltf_state == htf_state:
        ltf_role = "continuation"
        aligned = True
    else:
        ltf_role = "unclear"
        aligned = False

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
    return "Ambiguous alignment — wait for clearer structure on LTF."
