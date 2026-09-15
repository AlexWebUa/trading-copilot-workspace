"""
30mOF — the trader's order-flow setup, third of his own setups to be formalised.

Spec and its verification: `docs/SETUP_30MOF.md`. Everything here comes from his
answers of 2026-08-26 plus a two-day markup (25-27 July) he walked bar by bar,
which is pinned as a golden test in `tests/test_detectors_order_flow.py`.

Shape of the setup — all of it on 30m, no OTT, no session or day levels:

    context     a confirmed order flow: a BOS starts it, two cBOS confirm it.
                `detect_order_flow.confirmed` is that gate.
    frequency   trade until the structure breaks OR until the flow takes a pool
                that predates it; after that, wait for one more confirmation.
                `entries_allowed` carries the whole rule.
    entry       market on the continuation, or from a POI price retraces into.
    stop        behind the live counter key ("свежая сильная точка"), за фитилём.
    target      the nearest unswept fractal paying >= 1.8R.

STAGE 1 (agreed with the trader, `docs/SETUP_30MOF.md`): the target policy is
FIXED at `nearest_fractal` and only the seven entry models are compared, two
sides each — 14 arms. Only the entry models that survive get the second target
policy (`rr:1.8`) in stage 2. Running all 28 at once would put one or two false
positives in the results by construction: Silver Bullet's twelve arms already
produced exactly one borderline "edge" that had to be thrown away on those
grounds.
"""

from __future__ import annotations

from copilot.backtest.rules import Condition, SetupRule

# 3-candle fractals on 30m — the setup's own, verified against the trader's
# markup. Every condition touching the flow must carry it or it measures a
# different structure than the one he reads.
# History is walked in FULL (`lookback=0`), which costs ~18 min per arm on a
# year of 30m data. The STRUCTURE converges early — direction, confirmations and
# both key points are identical from a 600-bar warm-up on — but the POOL does
# not, and the pool gate is the setup's frequency rule, not a detail.
#
# `scripts/measure_of_lookback.py` re-measured this against the unbounded walk
# over 500 slices of the research year (`research/runs/of_lookback.json`):
#
#     window   entries_allowed   pool_level
#       1000        89%             55%
#       2000        95%             77%
#       4000        98%             91%
#       6000       100%             98%
#       8000       100%            100%
#
# So `lookback=8000` reproduces the unbounded walk exactly on that sample and
# turns the sweep from quadratic into linear — which is what makes a two- or
# three-year window affordable at all (3 years unbounded is ~9x a year; bounded
# at 8000 it is ~2.7x). Kept at 0 here so the 2026-08-27 results stay
# reproducible from this file; switch it deliberately, and re-verify the
# convergence on the longer window, since pools there can be older than
# anything this measurement saw.
_FRACTAL_3 = {"swing_lookback": 1, "lookback": 0}

# Entry models. The key is the arm suffix; the value is `entry_after`.
#   market    — fill at the close of the bar whose body confirmed the cBOS
#   *_near    — a limit at the near edge of the zone, filled when price touches
#   fvg_full  — the imbalance has to be closed completely before filling
_ENTRY_MODELS: dict[str, str] = {
    "market":   "signal_close",
    "poi":      "poi_near",
    "fvg":      "fvg_near",
    "fvg_full": "fvg_full",
    "bpr":      "bpr_near",
    "ob":       "ob_near",
    "stb":      "stb_bts_near",
}

# How long a resting limit stays live. 20 bars of 30m = 10 hours: long enough
# for a normal retracement, short enough that the POI still belongs to the leg
# that created it.
_MAX_WAIT_BARS = 20

# Minimum stop, in ATR. The trader's rule of 2026-08-27, after run 1 showed a
# POI entry can sit on the structural key and leave $0.90 of risk: widen the
# stop to a minimum rather than skip the trade, and let `min_rr` re-judge the
# trade against the widened stop. Run 1's POI numbers were produced WITHOUT
# this and are not comparable to anything measured after it.
_MIN_STOP_ATR = 0.5


# Stage 1b — the paired "touch or full fill?" question. Stage 1 tests every POI
# on touch and only FVG on full fill, so on its own it cannot say whether the
# fill rule matters. These four complete the pairs.
#
# Read them PAIRED, against the same POI's touch arm from stage 1 — not as eight
# fresh candidates. The two arms of a pair trade the same signals and differ
# only in fill price, so the honest question is "does waiting for the far edge
# improve this POI", asked four times, not "did any of these twelve arms clear
# the bar", asked twelve times.
_ENTRY_MODELS_FULLFILL: dict[str, str] = {
    "poi_full": "poi_full",
    "bpr_full": "bpr_full",
    "ob_full":  "ob_full",
    "stb_full": "stb_bts_full",
}


def _30mof(name: str, direction: str, entry_after: str, tp_logic: str) -> SetupRule:
    long_side = direction == "long"
    flow_dir = "bullish" if long_side else "bearish"

    conditions = [
        # The flow must exist, point our way, and be confirmed by two cBOS.
        Condition("detect_order_flow", "direction", "eq", flow_dir, _FRACTAL_3),
        Condition("detect_order_flow", "confirmed", "true", None, _FRACTAL_3),
        # The frequency rule: a flow that has taken a pre-existing pool is done
        # until it proves otherwise. On 12 Jul this is the difference between no
        # trade and a losing one.
        Condition("detect_order_flow", "entries_allowed", "true", None, _FRACTAL_3),
        # The signal bar is the continuation itself.
        Condition("detect_order_flow", "events.0.type", "eq", "cBOS", _FRACTAL_3),
        Condition("detect_order_flow", "events.0.direction", "eq", flow_dir, _FRACTAL_3),
    ]

    return SetupRule(
        name=name,
        direction=direction,
        risk_pct=1.0,
        min_rr=1.8,

        htf_conditions=[],
        conditions=conditions,

        entry_after=entry_after,
        max_entry_wait_bars=_MAX_WAIT_BARS,

        sl_logic="of_key",
        min_stop_atr=_MIN_STOP_ATR,
        tp_logic=tp_logic,
        tp_levels=[],          # no partials
        sl_after_tp1=None,     # no break-even, as in every other setup of his
    )


def _arms(
    tp_logic: str,
    suffix: str,
    models: dict[str, str] | None = None,
) -> dict[str, SetupRule]:
    out: dict[str, SetupRule] = {}
    for model, entry_after in (models or _ENTRY_MODELS).items():
        for direction in ("long", "short"):
            name = f"of30_{model}_{direction}{suffix}"
            out[name] = _30mof(name, direction, entry_after, tp_logic)
    return out


# Stage 1 — 14 arms, target fixed to the nearest fractal paying min_rr.
STAGE1_RULES: dict[str, SetupRule] = _arms("nearest_fractal", "")

# Stage 1b — 8 arms, same target policy as stage 1 so the pairs are comparable.
STAGE1B_RULES: dict[str, SetupRule] = _arms(
    "nearest_fractal", "", _ENTRY_MODELS_FULLFILL
)

# Stage 2 — the same entry models against a flat 1.8R target. NOT to be run as
# one 28-arm sweep: only the models that survive stage 1 belong here.
STAGE2_RULES: dict[str, SetupRule] = _arms("rr:1.8", "_rr")

RULES_30MOF: dict[str, SetupRule] = {**STAGE1_RULES, **STAGE1B_RULES, **STAGE2_RULES}
