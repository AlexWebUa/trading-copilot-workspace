"""
ICT Silver Bullet — the first of the common ICT strategies to be formalised.

Source: knowledge_base/08_Entry_Models/ICT_Silver_Bullet.md, plus the trader's
decisions of 2026-08-23 and his verified 11-Aug reference trade
(docs/SETUP_ICT_SILVER_BULLET.md).

What the reference trade settled, and why each choice is not obvious:

  timing      — only the FILL has to land inside the window. On 11 Aug the
                sweep was at 02:45 NY and the BOS at 02:57, both BEFORE the
                03:00-04:00 London Open window; only the test entry at 03:12
                was inside it. Gating the signal instead of the fill would
                delete the trade.
  anchoring   — windows are New York hours, not Kyiv. The note's Kyiv column
                (10:00-11:00 winter / 11:00-12:00 summer) is wrong: Kyiv and NY
                shift together, so EST 03:00 is Kyiv 10:00 year-round, and the
                11-Aug fill at Kyiv 10:12 = NY 03:12 confirms it.
  pools       — plain 3-candle fractals. The note lists five pool types
                (EQH/EQL, compression, 15M swings, PDH/PDL, London H/L), but
                the trader's own pool and target were the Asian low and high,
                which are neither — and both turned out to be ordinary 3-candle
                fractals on 15m. "A session extreme is a fractal too", so one
                detector covers the whole taxonomy and no session logic is
                needed.
  target      — nearest fractal that pays min_rr. Literally-nearest is usually
                unreachable: on 11 Aug the nearest three paid 0.74R / 0.97R /
                1.02R against the 1.3 floor.
  min_rr      — 1.3, NOT the 1.8 of the rest of the research frame. Silver
                Bullet is built on "low hanging fruit" targets; forcing 1.8
                would test a different strategy.

Deliberately absent:
  news        — "новости не торгуются" cannot be implemented, there is no
                economic calendar in the system. NFP days sit in the sample as
                ordinary days.
  pre-timing  — "skip the window if a swing/news move preceded it" was dropped
    swing       by the trader (2026-08-23).
  break-even  — the note lists five BE triggers; the research frame forbids BE.
"""

from __future__ import annotations

from copilot.backtest.rules import Condition, SetupRule

# 3-candle fractals everywhere in this setup — pools on 15m and entry
# structure on 3m alike. swing_lookback counts bars on EACH SIDE, so 3-candle
# is 1 (see docs/SETUP_1H3M_BELLISSIMO.md for the terminology table).
_FRACTAL_3 = {"swing_lookback": 1}

# New York hours [start, end). The three Silver Bullet timings.
TIMINGS: dict[str, tuple[int, int]] = {
    "london": (3, 4),    # 03:00-04:00 NY — London Open
    "nyam": (10, 11),    # 10:00-11:00 NY
    "nypm": (14, 15),    # 14:00-15:00 NY
}

# Market vs test are two different execution models, not a parameter: on the
# 11-Aug example the market fill would have been outside the window entirely.
ENTRY_MODES: dict[str, str] = {
    "mkt": "signal_close",
    "test": "fvg_near",
}


def _silver_bullet(timing: str, entry_mode: str, direction: str) -> SetupRule:
    long_side = direction == "long"
    sweep_side = "sellside" if long_side else "buyside"
    reaction = "bullish" if long_side else "bearish"
    continuation = "bearish" if long_side else "bullish"

    return SetupRule(
        name=f"sb_{timing}_{entry_mode}_{direction}",
        direction=direction,
        risk_pct=1.0,
        # The setup's own floor, not the frame's 1.8 — see module docstring.
        min_rr=1.3,

        htf_conditions=[],
        conditions=[
            # A sweep of a 3-candle fractal pool on 15m. detect_liquidity
            # reports wick-past-and-close-back only, so "taken without closing
            # through" is already its definition.
            Condition("detect_liquidity", "recent_sweeps.0.side", "eq", sweep_side, _FRACTAL_3),
            # Re-sweep guard: the candle that took the liquidity must not have
            # printed a new equal extreme of its own, or price is being invited
            # straight back to take it.
            Condition(
                "detect_liquidity", "recent_sweeps.0.forms_equal_extreme",
                "false", kwargs=dict(_FRACTAL_3),
            ),
        ],
        entry_after="signal_close",

        entry_tf="3m",
        entry_conditions=[
            # Swing BOS against the sweep, confirmed by a body close.
            Condition("detect_bos", "events.0.direction", "eq", reaction, _FRACTAL_3),
            Condition(
                "detect_bos", "events.0.broken_level",
                "gt" if long_side else "lt",
                kwargs=dict(_FRACTAL_3),
                value_ref="signal:detect_liquidity.recent_sweeps.0.swept_level",
            ),
        ],
        invalidation_conditions=[
            Condition("detect_bos", "events.0.direction", "eq", continuation, _FRACTAL_3),
        ],
        entry_after_ltf=ENTRY_MODES[entry_mode],
        # One hour of 3m bars: the fill must happen inside a one-hour timing,
        # so waiting longer than the window itself cannot produce a valid trade.
        max_entry_wait_bars_ltf=20,

        sl_logic="sweep_fractal",
        tp_logic="nearest_fractal",
        tp_levels=[],
        sl_after_tp1=None,

        required_entry_hours_ny=TIMINGS[timing],
    )


# 3 timings x 2 entry models x 2 directions. The timings are separate arms
# rather than one pooled statistic because London Open and NY PM are different
# regimes and pooling them would hide it.
SILVER_BULLET_RULES: dict[str, SetupRule] = {
    rule.name: rule
    for rule in (
        _silver_bullet(t, m, d)
        for t in TIMINGS
        for m in ENTRY_MODES
        for d in ("long", "short")
    )
}
