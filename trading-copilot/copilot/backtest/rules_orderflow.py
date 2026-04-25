"""
Orderflow-enhanced SetupRules — Phase 6.

Three groups based on the type of orderflow filter added to SMC core logic:

  Group A — VP Context Filters  (Volume Profile as market-regime qualifier)
  Group B — CD Confirmation Filters  (Cumulative Delta as signal legitimacy check)
  Group C — Combined VP + CD  (highest selectivity, lowest frequency)

Import these alongside BUILTIN_RULES for comparison runs:

    from copilot.backtest.rules import BUILTIN_RULES
    from copilot.backtest.rules_orderflow import ORDERFLOW_RULES
    all_rules = {**BUILTIN_RULES, **ORDERFLOW_RULES}
"""

from __future__ import annotations

from copilot.backtest.rules import Condition, SetupRule

# ---------------------------------------------------------------------------
# Group A — VP Context Filters
# ---------------------------------------------------------------------------

# Rule A1: OB inside HVN long
# Bullish MS + BOS + FVG + unmitigated bullish OB that sits inside an HVN.
# VP confirms the OB zone has historical volume acceptance — double structural backing.
_ob_in_hvn_long = SetupRule(
    name="ob_in_hvn_long",
    direction="long",
    conditions=[
        Condition("detect_market_structure", "state", "eq", "bullish"),
        Condition("detect_bos", "direction", "eq", "bullish"),
        Condition("detect_bos", "type", "not_in", ["none"]),
        Condition("detect_fvg", "count_active", "gt", 0),
        Condition("detect_fvg", "fvgs.0.type", "eq", "bullish"),
        Condition("detect_order_block", "obs.0.type", "eq", "bullish"),
        Condition("detect_order_block", "obs.0.is_mitigated", "false"),
        Condition("check_ob_in_hvn", "in_hvn", "true"),
    ],
    entry_after="fvg_ce",
    sl_logic="ob",
    tp_logic="liquidity",
    required_session=None,
)

# Rule A2: POC discount BOS long
# Bullish MS + strong BOS (≥1.0 ATR displacement) + bullish FVG.
# VP gate: buying below POC = buying in the value zone where institutions accepted price.
_poc_discount_bos_long = SetupRule(
    name="poc_discount_bos_long",
    direction="long",
    conditions=[
        Condition("detect_market_structure", "state", "eq", "bullish"),
        Condition("detect_bos", "direction", "eq", "bullish"),
        Condition("detect_bos", "type", "not_in", ["none"]),
        Condition("detect_bos", "displacement_atr_multiple", "gte", 1.0),
        Condition("detect_fvg", "count_active", "gt", 0),
        Condition("detect_fvg", "fvgs.0.type", "eq", "bullish"),
        Condition("check_poc_location", "in_discount", "true"),
    ],
    entry_after="fvg_ce",
    sl_logic="swing",
    tp_logic="next_hvn",
    required_session=None,
)

# Rule A3: LVN acceleration long
# Bullish MS + strong BOS (≥1.5 ATR) + price currently in an LVN.
# LVN = thin-volume zone → price accelerates through it toward the next HVN.
# Tight SL (atr:1.0) because fast reversals if the LVN doesn't hold.
_lvn_acceleration_long = SetupRule(
    name="lvn_acceleration_long",
    direction="long",
    conditions=[
        Condition("detect_market_structure", "state", "eq", "bullish"),
        Condition("detect_bos", "direction", "eq", "bullish"),
        Condition("detect_bos", "type", "not_in", ["none"]),
        Condition("detect_bos", "displacement_atr_multiple", "gte", 1.5),
        Condition("check_price_in_lvn", "in_lvn", "true"),
    ],
    entry_after="next_open",
    sl_logic="atr:1.0",
    tp_logic="next_hvn",
    required_session=None,
)

# Rule A4: VAH rejection short (bearish mirror of A2)
# Bearish or ranging MS + bearish BOS + bearish FVG.
# VP gate: price above POC = premium = overextended above institutional value area.
_vah_rejection_short = SetupRule(
    name="vah_rejection_short",
    direction="short",
    conditions=[
        Condition("detect_market_structure", "state", "in", ["bearish", "ranging"]),
        Condition("detect_bos", "direction", "eq", "bearish"),
        Condition("detect_bos", "type", "not_in", ["none"]),
        Condition("detect_fvg", "count_active", "gt", 0),
        Condition("detect_fvg", "fvgs.0.type", "eq", "bearish"),
        Condition("check_poc_location", "in_premium", "true"),
    ],
    entry_after="fvg_ce",
    sl_logic="ob",
    tp_logic="liquidity",
    required_session=None,
)


# ---------------------------------------------------------------------------
# Group B — CD Confirmation Filters
# ---------------------------------------------------------------------------

# Rule B1: Sweep + CD manipulation confirmed long  ← highest-conviction hypothesis
# Sellside sweep → the wick went below a prior low, BUT CD was NEGATIVE on that bar
# (sellers dominated = institutional manipulation, not organic selling).
# Core: bullish MS + bullish BOS + bullish FVG.
# Requires delta columns → delta-aware engine fetch triggered automatically.
_sweep_cd_manipulation_long = SetupRule(
    name="sweep_cd_manipulation_long",
    direction="long",
    conditions=[
        Condition("detect_market_structure", "state", "eq", "bullish"),
        Condition("detect_bos", "direction", "eq", "bullish"),
        Condition("detect_bos", "type", "not_in", ["none"]),
        Condition("detect_fvg", "count_active", "gt", 0),
        Condition("detect_fvg", "fvgs.0.type", "eq", "bullish"),
        # CD manipulation: sweep + contradicting delta → institutional print
        Condition("detect_cumulative_delta", "sweep_confirmation.sweep_side", "eq", "sellside"),
        Condition("detect_cumulative_delta", "sweep_confirmation.confirmed_manipulation", "true"),
    ],
    entry_after="fvg_ce",
    sl_logic="swing",
    tp_logic="rr:2.0",
    required_session=["london_open", "ny_am", "ny_pm"],
)

# Rule B2: BOS + CD confluence long
# Bullish MS + strong BOS + bullish FVG + CD trend positive (volume backs the break).
# Filters out liquidity-driven false BOS where CD doesn't agree with direction.
_bos_cd_confluence_long = SetupRule(
    name="bos_cd_confluence_long",
    direction="long",
    conditions=[
        Condition("detect_market_structure", "state", "eq", "bullish"),
        Condition("detect_bos", "direction", "eq", "bullish"),
        Condition("detect_bos", "type", "not_in", ["none"]),
        Condition("detect_bos", "displacement_atr_multiple", "gte", 1.0),
        Condition("detect_fvg", "count_active", "gt", 0),
        Condition("detect_fvg", "fvgs.0.type", "eq", "bullish"),
        # CD agrees with BOS direction → volume-backed break
        Condition("detect_cumulative_delta", "delta_trend", "eq", "positive"),
    ],
    entry_after="fvg_ce",
    sl_logic="swing",
    tp_logic="rr:2.0",
    required_session=None,
)

# Rule B3: CD bearish divergence + OB short
# CD bearish divergence (price new high, CD falling) = momentum exhaustion signal.
# Context: bearish/ranging MS + bearish OB + bearish BOS confirms the reversal.
_cd_divergence_ob_short = SetupRule(
    name="cd_divergence_ob_short",
    direction="short",
    conditions=[
        Condition("detect_market_structure", "state", "in", ["bearish", "ranging"]),
        Condition("detect_bos", "direction", "eq", "bearish"),
        Condition("detect_bos", "type", "not_in", ["none"]),
        Condition("detect_order_block", "obs.0.type", "eq", "bearish"),
        Condition("detect_order_block", "obs.0.is_mitigated", "false"),
        # CD divergence: price rising, delta falling = buyers running out
        Condition("detect_cumulative_delta", "divergences.0.type", "eq", "bearish"),
    ],
    entry_after="next_open",
    sl_logic="ob",
    tp_logic="liquidity",
    required_session=None,
)


# ---------------------------------------------------------------------------
# Group C — Combined VP + CD (highest selectivity)
# ---------------------------------------------------------------------------

# Rule C1: Sponsored candle OB in HVN long  ← combined highest-quality OB
# Requires: sponsored OB (sweep preceded it) + that OB in HVN + absorption bar
# + bullish FVG. All four elements must align.
# Expected: 2-5 signals/month on BTCUSDT 1h; hypothesis PF ≥ 3.0
_sponsored_cd_ob_hvn_long = SetupRule(
    name="sponsored_cd_ob_hvn_long",
    direction="long",
    conditions=[
        Condition("detect_market_structure", "state", "eq", "bullish"),
        # Sponsored candle = OB preceded by confirmed liquidity sweep (highest-quality OB)
        Condition("detect_sponsored_candle", "count", "gt", 0),
        Condition("detect_sponsored_candle", "candles.0.ob_type", "eq", "bullish"),
        # VP: sponsored OB sits inside an HVN (double structural backing)
        Condition("check_ob_in_hvn", "in_hvn", "true"),
        # Absorption: high-vol, small-range, close near high = hidden buyers absorbing
        Condition("check_cd_absorption", "absorption_detected", "true"),
        # FVG in displacement after the sponsored candle
        Condition("detect_fvg", "count_active", "gt", 0),
        Condition("detect_fvg", "fvgs.0.type", "eq", "bullish"),
    ],
    entry_after="fvg_ce",
    sl_logic="ob",
    tp_logic="liquidity",
    required_session=["london_open", "ny_am"],
)

# Rule C2: Compression breakout into LVN long
# Compression squeeze → strong expansion BOS (≥2.0 ATR) → price in LVN (fast move)
# → CD positive confirms the expansion → bullish FVG in the impulse.
_compression_vp_break_long = SetupRule(
    name="compression_vp_break_long",
    direction="long",
    conditions=[
        Condition("detect_market_structure", "state", "eq", "bullish"),
        # Compression: squeeze preceding the expansion
        Condition("detect_compression", "active", "true"),
        # Strong BOS breaking out of the compression (≥2.0 ATR displacement)
        Condition("detect_bos", "direction", "eq", "bullish"),
        Condition("detect_bos", "displacement_atr_multiple", "gte", 2.0),
        # LVN: price in thin-volume zone after breakout (momentum expected)
        Condition("check_price_in_lvn", "in_lvn", "true"),
        # CD confirms the expansion with rising buying pressure
        Condition("detect_cumulative_delta", "delta_trend", "eq", "positive"),
        # FVG in the expansion impulse to target for entry
        Condition("detect_fvg", "count_active", "gt", 0),
        Condition("detect_fvg", "fvgs.0.type", "eq", "bullish"),
    ],
    entry_after="fvg_ce",
    sl_logic="swing",
    tp_logic="next_hvn",
    required_session=["london_open", "ny_am"],
)


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------

ORDERFLOW_RULES: dict[str, SetupRule] = {
    # Group A — VP Context
    "ob_in_hvn_long": _ob_in_hvn_long,
    "poc_discount_bos_long": _poc_discount_bos_long,
    "lvn_acceleration_long": _lvn_acceleration_long,
    "vah_rejection_short": _vah_rejection_short,
    # Group B — CD Confirmation
    "sweep_cd_manipulation_long": _sweep_cd_manipulation_long,
    "bos_cd_confluence_long": _bos_cd_confluence_long,
    "cd_divergence_ob_short": _cd_divergence_ob_short,
    # Group C — Combined VP + CD
    "sponsored_cd_ob_hvn_long": _sponsored_cd_ob_hvn_long,
    "compression_vp_break_long": _compression_vp_break_long,
}

# Convenience: rules grouped by category for --group A/B/C in compare command
ORDERFLOW_GROUPS: dict[str, list[str]] = {
    "A": ["ob_in_hvn_long", "poc_discount_bos_long", "lvn_acceleration_long", "vah_rejection_short"],
    "B": ["sweep_cd_manipulation_long", "bos_cd_confluence_long", "cd_divergence_ob_short"],
    "C": ["sponsored_cd_ob_hvn_long", "compression_vp_break_long"],
}
