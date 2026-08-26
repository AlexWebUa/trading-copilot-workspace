"""
1h3m Bellissimo — the first of the trader's own setups to be formalised.

Source: knowledge_base/09_Setups/1h3m_by_Bellissimo.md, plus the author's own
clarifications (2026-08-22) on the four points the note left open:

  m3m3          — after the 1h sweep, wait for a 3m BOS in the direction of
                  context. If instead price only sweeps on 3m and BOSes the
                  other way, the reaction never came → abandon the signal.
  raid quality  — it is the SWEPT LIQUIDITY that must be quality, not the raid:
                  a 5-bar fractal, PDH/PDL, or EQH/EQL with 2+ touches.
  FTA           — counter-trend POI (FVG, OB and derivatives). If one sits
                  before the target and the trade can still close inside it at
                  >= min_rr, that is the take. No partial exits.
  context       — synchronise, never fade: a long looks for a sweep of BEARISH
                  (sellside) liquidity plus a 3m bullish BOS. 1W/1D agreement is
                  preferred, and is a separate variant so its value is measurable.

Fixed research frame (docs/RESEARCH_PROTOCOL.md § 2.6): BTCUSDT only, risk 1%,
min R:R 1.8, no partials, no break-even.

Two TP policies ship as separate rules because that is an open question of the
methodology, not a condition ablation can remove:
  *_fta_skip   — an FTA too close to pay 1.8R kills the trade
  *_fta_thru   — the same FTA is ignored and the liquidity behind it is targeted

Everything else (the 1W filter, m3m3, the liquidity-quality conditions, the OTT
window) is an ordinary condition, so `compare --ablate` can measure each one's
contribution instead of us guessing.
"""

from __future__ import annotations

from copilot.backtest.rules import AnyOf, Condition, HTFCondition, SetupRule

# swing_lookback counts bars on EACH SIDE of the pivot, so a 5-bar (Williams)
# fractal is swing_lookback=2 — verified against detect_fractals(bars="5") and
# on a synthetic pivot that survives ±2 but not ±3. The detector's own default
# of 3 is a 7-bar formation: stricter than the setup asks for, not looser.
# Every condition touching detect_liquidity must carry this or it measures a
# different kind of pool than the setup describes.
_FRACTAL_5 = {"swing_lookback": 2}

# Entry fractals on 3M are ALWAYS 3-candle in this setup — and swing_lookback
# counts bars on each side, so 3-candle is 1, not 3 (which is a 7-candle pivot).
_FRACTAL_3 = {"swing_lookback": 1}

# 09:00–23:00 Kyiv — widened from the note's 09:00–17:00 after the trader's
# reference trade (1 Aug) turned out to fire at 21:00, well outside it. 23:00 is
# the New York close.
_OTT_HOURS = (9, 23)


def _bellissimo(name: str, direction: str, tp_logic: str = "fractal_or_fta") -> SetupRule:
    long_side = direction == "long"

    # Context: a long sweeps SELLSIDE liquidity (takes lows) and continues up.
    sweep_side = "sellside" if long_side else "buyside"
    pool_field = "sellside_liquidity" if long_side else "buyside_liquidity"
    pool_types = ["EQL", "swing_low"] if long_side else ["EQH", "swing_high"]
    # A long takes lows, so the previous day's LOW is the daily pool in play.
    # Day boundary is UTC (the trader's choice, 2026-08-22) — the detector's default.
    pd_field = "pdl_swept" if long_side else "pdh_swept"
    # The reaction we need is AGAINST the sweep; continuation in the sweep's
    # own direction is what invalidates the setup.
    reaction_state = "bullish" if long_side else "bearish"
    continuation_state = "bearish" if long_side else "bullish"

    # The 1D context filter is gone (trader's call, 2026-08-22): daily structure
    # was genuinely bearish through the sample, so as a hard gate it simply
    # deleted the long side rather than describing it. 1H is the context
    # timeframe of the setup anyway ("only 1H + 3M").
    # No HTF gate at all. 1D was dropped first (it deleted the long side through
    # a bearish sample), then 1W (47 signals → 2), then the 1H context itself:
    # counter-context trades do work, and the sample needs the volume. Bring the
    # 1H context back only if counter-trend entries turn out to stop out often.
    htf: list[HTFCondition] = []

    return SetupRule(
        name=name,
        direction=direction,
        risk_pct=1.0,
        min_rr=1.8,

        htf_conditions=htf,
        conditions=[
            # The ONLY entry trigger on 1H: a sweep. Direction is set by the
            # sweep itself — lows taken → look long, highs taken → look short.
            # detect_liquidity reports only wick-and-close-back as a sweep, so
            # "taken without an hourly close through it" is already its definition.
            # The pool may be of ANY age: requiring it to be same-day was a
            # coding error and is gone.
            Condition("detect_liquidity", "recent_sweeps.0.side", "eq", sweep_side, _FRACTAL_5),
            # Raid quality — the SWEPT liquidity has to be worth taking, and the
            # author's criteria are alternatives, not a conjunction: a 5-bar
            # fractal swing, OR equal highs/lows with 2+ touches, OR PDH/PDL.
            AnyOf([
                Condition("detect_liquidity", f"{pool_field}.0.touches", "gte", 2, _FRACTAL_5),
                Condition("detect_liquidity", f"{pool_field}.0.type", "eq", pool_types[1], _FRACTAL_5),
                # PDH/PDL: ask the day-levels detector whether the previous day's
                # extreme was the thing taken, rather than float-comparing prices.
                Condition("detect_previous_day_levels", pd_field, "true"),
            ]),
        ],

        # The HTF signal bar only arms the setup; the actual fill is decided on
        # 3M by entry_after_ltf, so this slot is a formality for LTF rules.
        entry_after="signal_close",

        # Entry on 3M
        entry_tf="3m",
        entry_conditions=[
            # BOS on 3M AGAINST the direction of the sweep — the reaction.
            Condition("detect_bos", "events.0.direction", "eq", reaction_state, _FRACTAL_3),
            # … and beyond the raided level.
            Condition(
                "detect_bos", "events.0.broken_level",
                "gt" if long_side else "lt",
                kwargs=dict(_FRACTAL_3),
                value_ref="signal:detect_liquidity.recent_sweeps.0.swept_level",
            ),
        ],
        invalidation_conditions=[
            # A 3M BOS in the SAME direction as the sweep means price simply
            # carried on — there was no reaction, so there is no setup.
            Condition("detect_bos", "events.0.direction", "eq", continuation_state, _FRACTAL_3),
        ],
        entry_after_ltf="signal_close",   # entry by market
        max_entry_wait_bars_ltf=20,       # 20 × 3m = 1 hour (trader's call)

        sl_logic="sweep_fractal",         # behind the fractal that took the liquidity
        tp_logic=tp_logic,
        tp_levels=[],                     # no partials
        sl_after_tp1=None,                # no break-even, by the author's rule

        required_hours_kyiv=_OTT_HOURS,
    )


# Two arms, one per side. The fta_skip / fta_thru split is gone: the target rule
# is now a single policy ("nearest fractal paying 1.8R, else 1.8R inside the
# obstacle"), so there is nothing left to A/B there.
# Four arms: both directions x both FTA policies. The FTA split is back —
# not as a methodology hedge this time, but because the strict reading vetoed
# the trader's own validated 1-Aug trade (an imbalance 34 points above entry,
# paying 0.16R, outranked a clean 2.62R fractal target). Which reading is
# right is exactly what he asked to measure, so both run.
BELLISSIMO_RULES: dict[str, SetupRule] = {
    rule.name: rule
    for rule in (
        _bellissimo("bellissimo_1h3m_long", "long"),
        _bellissimo("bellissimo_1h3m_short", "short"),
        _bellissimo("bellissimo_1h3m_long_softfta", "long", "fractal_or_fta_soft"),
        _bellissimo("bellissimo_1h3m_short_softfta", "short", "fractal_or_fta_soft"),
    )
}
