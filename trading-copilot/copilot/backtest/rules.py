"""
SetupRule and Condition — declarative detector-confluence requirements.

A SetupRule describes a trading setup as a list of Conditions (each asserting
a field of a detector's output dict), plus entry/SL/TP logic strings and
optional session/killzone filters.

Conditions are evaluated bar-by-bar inside BacktestEngine: if all pass, a
trade signal is generated. Detectors are called directly (no LLM, no API),
each at most once per bar.
"""

from __future__ import annotations

import importlib
import json
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Any

import copilot.detectors as _detectors_pkg

logger = logging.getLogger(__name__)

# Sentinel for a missing field — distinguishable from None
_MISSING = object()

# Detectors that require delta columns (buy_vol/sell_vol/delta) — excluded from backtest
_DELTA_ONLY = {"detect_cumulative_delta"}

# Detectors that take no DataFrame — excluded from condition evaluation
_NO_DF = {"check_multi_tf_alignment", "current_killzone"}

_VALID_OPS = frozenset(
    {
        "eq", "ne", "gt", "lt", "gte", "lte", "in", "not_in", "exists", "true", "false",
        # Temporal: the field is an ISO timestamp, compared against the current bar.
        # "Only a fractal of the CURRENT day counts; yesterday's is not a factor"
        # cannot be written any other way — the DSL compares to constants, and
        # "today" is not a constant.
        "same_day", "not_same_day",
    }
)
_VALID_DIRECTIONS = frozenset({"long", "short"})
_VALID_REF_NAMESPACES = frozenset({"self", "signal"})
_VALID_ENTRY_AFTER = frozenset({"next_open", "signal_close", "fvg_ce", "ob_midpoint"})
# "fvg_near" rests a limit on the near edge of the imbalance printed during
# the LTF confirmation and fills only if price trades back into it — the
# "test" entry of Silver Bullet, as opposed to filling at market.
_VALID_ENTRY_AFTER_LTF = frozenset({"signal_close", "next_open", "fvg_near"})


class RuleConfigError(ValueError):
    """Raised when a SetupRule has invalid configuration."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Condition:
    """
    A single assertion on one field of one detector's output dict.

    field: dotted path, e.g. "state", "fvgs.0.type", "obs.0.is_mitigated"
    op:    one of eq|ne|gt|lt|gte|lte|in|not_in|exists|true|false
    value: comparison value; ignored / should be None for exists/true/false
    kwargs: extra kwargs forwarded to the detector call
    """
    detector: str
    field: str
    op: str
    value: Any = None
    kwargs: dict = field(default_factory=dict)
    # Compare against ANOTHER detector's field instead of a constant.
    #   "self:detect_bos.events.0.broken_level"   — same slice / same timeframe
    #   "signal:detect_liquidity.recent_sweeps.0.swept_level"
    #                                             — the HTF signal bar's cache
    # "3m BOS is above the raid" is two moving values on two timeframes; with a
    # constant-only DSL it could not be written at all.
    value_ref: str | None = None

    def __post_init__(self) -> None:
        if self.value_ref is not None:
            ns = self.value_ref.split(":", 1)[0]
            if ns not in _VALID_REF_NAMESPACES:
                raise RuleConfigError(
                    f"Condition.value_ref namespace {ns!r} invalid. "
                    f"Valid: {sorted(_VALID_REF_NAMESPACES)}"
                )
        if self.op not in _VALID_OPS:
            raise RuleConfigError(
                f"Condition.op '{self.op}' invalid. Valid: {sorted(_VALID_OPS)}"
            )

    def evaluate(self, result: dict, now_ts: Any = None) -> bool:
        val = _get_field(result, self.field)
        return _check_op(val, self.op, self.value, now_ts)

    def to_dict(self) -> dict:
        return {
            "detector": self.detector,
            "field": self.field,
            "op": self.op,
            "value": self.value,
            "kwargs": self.kwargs,
            "value_ref": self.value_ref,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Condition":
        return cls(
            detector=d["detector"],
            field=d["field"],
            op=d["op"],
            value=d.get("value"),
            kwargs=d.get("kwargs", {}),
            value_ref=d.get("value_ref"),
        )


@dataclass
class AnyOf:
    """Passes when ANY of its conditions passes — an OR inside an AND list.

    "Quality liquidity" is a list of alternatives, not a conjunction: a 5-bar
    fractal, OR PDH/PDL, OR equal highs/lows with 2+ touches. With only AND
    available the rule would have demanded all three at once and taken almost
    nothing.
    """

    conditions: list["Condition"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"any_of": [c.to_dict() for c in self.conditions]}

    @classmethod
    def from_dict(cls, d: dict) -> "AnyOf":
        return cls(conditions=[Condition.from_dict(c) for c in d["any_of"]])


@dataclass
class HTFCondition:
    """Like Condition but evaluated on a separate higher-timeframe DataFrame."""
    detector: str
    field: str
    op: str
    value: Any = None
    kwargs: dict = field(default_factory=dict)
    htf_tf: str = "4h"

    def __post_init__(self) -> None:
        if self.op not in _VALID_OPS:
            raise RuleConfigError(
                f"HTFCondition.op '{self.op}' invalid. Valid: {sorted(_VALID_OPS)}"
            )

    def evaluate(self, result: dict) -> bool:
        val = _get_field(result, self.field)
        return _check_op(val, self.op, self.value)

    def to_dict(self) -> dict:
        return {
            "detector": self.detector,
            "field": self.field,
            "op": self.op,
            "value": self.value,
            "kwargs": self.kwargs,
            "htf_tf": self.htf_tf,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HTFCondition":
        return cls(
            detector=d["detector"],
            field=d["field"],
            op=d["op"],
            value=d.get("value"),
            kwargs=d.get("kwargs", {}),
            htf_tf=d.get("htf_tf", "4h"),
        )


@dataclass
class TPLevel:
    """A single take-profit level for multi-leg TP management."""
    logic: str      # same format as tp_logic: "rr:1.8", "liquidity", "next_hvn"
    size_pct: float  # fraction of position to close: 0.5 = 50%

    def to_dict(self) -> dict:
        return {"logic": self.logic, "size_pct": self.size_pct}

    @classmethod
    def from_dict(cls, d: dict) -> "TPLevel":
        return cls(logic=d["logic"], size_pct=d["size_pct"])


@dataclass
class SetupRule:
    """
    Declarative description of a trading setup.

    entry_after:
      "next_open"    — enter at open of bar after signal
      "signal_close" — enter at close of signal bar
      "fvg_ce"       — limit at 50% of the most recent bullish/bearish FVG
      "ob_midpoint"  — limit at midpoint of most recent unmitigated OB

    sl_logic:
      "atr:N"  — entry ± ATR(14)*N
      "pct:N"  — entry ± entry*(N/100)
      "swing"  — below/above last intact fractal swing
      "ob"     — below/above detected OB boundary
      "fvg"    — below/above FVG zone boundary

    tp_logic:
      "rr:N"       — fixed R:R ratio
      "liquidity"  — nearest unswept liquidity pool
      "next_hvn"   — nearest High Volume Node

    entry_tf / entry_conditions:
      When entry_tf is set, the engine uses a 3-tier flow:
        Signal TF conditions pass → _LTF_SCAN state → entry_conditions
        evaluated on LTF bars → entry triggered → LTF exit simulation.

    htf_conditions:
      Evaluated on a separate HTF DataFrame. All must pass on the same bar
      (after LTF conditions) for the signal to fire.

    tp_levels:
      Multi-leg TP. If non-empty, overrides tp_logic.
      Example: [TPLevel("rr:1.8", 0.5), TPLevel("rr:4.0", 0.5)]

    sl_after_tp1:
      SL logic after TP1 hit. "be" → breakeven, "atr:N" → trail. None = keep.

    max_bars_open:
      Close trade after this many signal-TF bars. None = no limit.

    fee_bps:
      Fee in basis points PER SIDE (e.g. 4.0 = 0.04% taker).
      Charged on both entry and exit notional.

    slippage_bps:
      Estimated slippage in basis points per side, applied like a fee
      on entry and exit notional.

    risk_pct:
      Risk per trade as % of account for reporting. Default 1%.
    """
    name: str
    direction: str
    conditions: list[Condition]
    entry_after: str
    sl_logic: str
    tp_logic: str
    required_session: list[str] | None = None
    # Explicit Kyiv-hour window [start, end). The session labels tile the day in
    # fixed blocks (ny_pm is 17-20, off_hours runs 20-02), so a window like
    # 09:00-23:00 cannot be expressed as a list of them without dragging in the
    # small hours. Takes precedence over required_session when set.
    required_hours_kyiv: tuple[int, int] | None = None
    # Explicit New-York-hour window [start, end) applied to the ENTRY bar, not
    # the signal bar. Silver Bullet needs both properties:
    #   - anchored to New York, because its timings are defined in EST/EDT and
    #     Kyiv drifts against NY for ~2 weeks a year around the DST switches;
    #   - checked at entry, because the trader's own reference trade swept and
    #     BOSed 15 and 3 minutes BEFORE the window and only the entry landed
    #     inside it ("главное зайти в пределах тайминга").
    required_entry_hours_ny: tuple[int, int] | None = None
    required_killzone: list[str] | None = None
    # Change 1: HTF conditions
    htf_conditions: list[HTFCondition] = field(default_factory=list)
    # Change 2: LTF entry confirmation
    entry_tf: str | None = None
    entry_conditions: list[Condition] = field(default_factory=list)
    # Conditions that ABANDON the signal while waiting for entry on the LTF.
    # Without these the LTF scan could only wait or time out, so a setup whose
    # invalidation fired first (price broke the other way, then came back inside
    # the wait window) was still entered — a trade the trader would never take.
    invalidation_conditions: list[Condition] = field(default_factory=list)
    entry_after_ltf: str = "signal_close"
    max_entry_wait_bars_ltf: int = 50
    # Change 3: Partial TP
    tp_levels: list[TPLevel] = field(default_factory=list)
    sl_after_tp1: str | None = None
    # Change 4: Time-based exit
    max_bars_open: int | None = None
    # Change 5: Fee model (per side; P0-6 June 2026: charged on entry AND exit)
    # Minimum planned reward:risk for the trade to be taken at all. The
    # trader's global floor (Aug 2026): below it the take is not "grammatical"
    # — typically the first opposing POI sits too close to entry. Was hard-coded
    # at 1.0 inside the engine, which silently took setups the trader would skip.
    min_rr: float = 1.8
    fee_bps: float = 0.0
    slippage_bps: float = 0.0
    # Change 6: Variable risk
    risk_pct: float = 1.0

    def validate(self) -> None:
        if self.direction not in _VALID_DIRECTIONS:
            raise RuleConfigError(f"direction '{self.direction}' must be 'long' or 'short'")
        if self.entry_after not in _VALID_ENTRY_AFTER:
            raise RuleConfigError(
                f"entry_after '{self.entry_after}' invalid. Valid: {sorted(_VALID_ENTRY_AFTER)}"
            )
        if not self.conditions:
            raise RuleConfigError(f"Rule '{self.name}' has no conditions")
        if self.entry_tf and self.entry_after_ltf not in _VALID_ENTRY_AFTER_LTF:
            raise RuleConfigError(
                f"entry_after_ltf '{self.entry_after_ltf}' invalid. "
                f"Valid: {sorted(_VALID_ENTRY_AFTER_LTF)}"
            )
        for htf_c in self.htf_conditions:
            if htf_c.op not in _VALID_OPS:
                raise RuleConfigError(f"HTFCondition.op '{htf_c.op}' invalid")
        for tp_lvl in self.tp_levels:
            if tp_lvl.size_pct <= 0 or tp_lvl.size_pct > 1:
                raise RuleConfigError(
                    f"TPLevel.size_pct {tp_lvl.size_pct} must be in (0, 1]"
                )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "direction": self.direction,
            "conditions": [c.to_dict() for c in self.conditions],
            "entry_after": self.entry_after,
            "sl_logic": self.sl_logic,
            "tp_logic": self.tp_logic,
            "required_session": self.required_session,
            "required_hours_kyiv": list(self.required_hours_kyiv) if self.required_hours_kyiv else None,
            "required_entry_hours_ny": (
                list(self.required_entry_hours_ny) if self.required_entry_hours_ny else None
            ),
            "required_killzone": self.required_killzone,
            "htf_conditions": [c.to_dict() for c in self.htf_conditions],
            "entry_tf": self.entry_tf,
            "entry_conditions": [c.to_dict() for c in self.entry_conditions],
            "invalidation_conditions": [c.to_dict() for c in self.invalidation_conditions],
            "entry_after_ltf": self.entry_after_ltf,
            "max_entry_wait_bars_ltf": self.max_entry_wait_bars_ltf,
            "tp_levels": [t.to_dict() for t in self.tp_levels],
            "sl_after_tp1": self.sl_after_tp1,
            "max_bars_open": self.max_bars_open,
            "min_rr": self.min_rr,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "risk_pct": self.risk_pct,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SetupRule":
        return cls(
            name=d["name"],
            direction=d["direction"],
            conditions=[_condition_from_dict(c) for c in d.get("conditions", [])],
            entry_after=d.get("entry_after", "next_open"),
            sl_logic=d.get("sl_logic", "atr:1.5"),
            tp_logic=d.get("tp_logic", "rr:2.0"),
            required_session=d.get("required_session"),
            required_hours_kyiv=(
                tuple(d["required_hours_kyiv"]) if d.get("required_hours_kyiv") else None
            ),
            required_entry_hours_ny=(
                tuple(d["required_entry_hours_ny"]) if d.get("required_entry_hours_ny") else None
            ),
            required_killzone=d.get("required_killzone"),
            htf_conditions=[HTFCondition.from_dict(c) for c in d.get("htf_conditions", [])],
            entry_tf=d.get("entry_tf"),
            entry_conditions=[_condition_from_dict(c) for c in d.get("entry_conditions", [])],
            invalidation_conditions=[
                _condition_from_dict(c) for c in d.get("invalidation_conditions", [])
            ],
            entry_after_ltf=d.get("entry_after_ltf", "signal_close"),
            max_entry_wait_bars_ltf=d.get("max_entry_wait_bars_ltf", 50),
            tp_levels=[TPLevel.from_dict(t) for t in d.get("tp_levels", [])],
            sl_after_tp1=d.get("sl_after_tp1"),
            max_bars_open=d.get("max_bars_open"),
            min_rr=d.get("min_rr", 1.8),
            fee_bps=d.get("fee_bps", 0.0),
            slippage_bps=d.get("slippage_bps", 0.0),
            risk_pct=d.get("risk_pct", 1.0),
        )


# ---------------------------------------------------------------------------
# Field navigation and operator evaluation
# ---------------------------------------------------------------------------

def _get_field(result: dict, path: str) -> Any:
    """
    Navigate a dotted path through nested dicts and lists.
    Returns _MISSING on any KeyError, IndexError, or TypeError — never raises.

    Examples:
      _get_field({"state": "bullish"}, "state")          → "bullish"
      _get_field({"fvgs": [{"type": "bullish"}]}, "fvgs.0.type") → "bullish"
      _get_field({}, "missing.key")                       → _MISSING
    """
    node: Any = result
    for token in path.split("."):
        if node is _MISSING:
            return _MISSING
        try:
            if isinstance(node, dict):
                node = node[token]
            elif isinstance(node, list):
                if token.isdigit():
                    node = node[int(token)]
                else:
                    # Search list for first element that has this key
                    found = _MISSING
                    for item in node:
                        if isinstance(item, dict) and token in item:
                            found = item[token]
                            break
                    node = found
            else:
                return _MISSING
        except (KeyError, IndexError, TypeError):
            return _MISSING
    return node


def _same_day(val: Any, now_ts: Any) -> bool:
    """True when *val* (an ISO timestamp) falls on the same UTC date as now_ts."""
    if val is _MISSING or val is None or now_ts is None:
        return False
    try:
        import pandas as _pd

        ts = _pd.Timestamp(val)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        ref = _pd.Timestamp(now_ts)
        if ref.tzinfo is None:
            ref = ref.tz_localize("UTC")
        return ts.tz_convert("UTC").date() == ref.tz_convert("UTC").date()
    except Exception:
        return False


def _check_op(val: Any, op: str, expected: Any, now_ts: Any = None) -> bool:
    """
    Evaluate a comparison operator against a field value.
    _MISSING → False for all operators except 'false' (where it → True, meaning absent=falsy).

    `now_ts` is the timestamp of the last bar in the evaluated slice; the
    temporal operators need it and nothing else does.
    """
    if op in ("same_day", "not_same_day"):
        same = _same_day(val, now_ts)
        return same if op == "same_day" else (not same)

    if op == "exists":
        return val is not _MISSING and val is not None
    if op == "true":
        return val is not _MISSING and bool(val) is True
    if op == "false":
        return val is _MISSING or bool(val) is False

    # For all comparison operators, _MISSING → False
    if val is _MISSING:
        return False

    try:
        if op == "eq":
            return val == expected
        if op == "ne":
            return val != expected
        if op == "gt":
            return val > expected
        if op == "lt":
            return val < expected
        if op == "gte":
            return val >= expected
        if op == "lte":
            return val <= expected
        if op == "in":
            return val in expected
        if op == "not_in":
            return val not in expected
    except TypeError:
        return False
    return False


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

def _condition_from_dict(d: dict):
    """Rebuild either a Condition or an AnyOf group from its serialised form."""
    return AnyOf.from_dict(d) if "any_of" in d else Condition.from_dict(d)


def flatten_conditions(items) -> list["Condition"]:
    """Expand AnyOf groups so callers that only understand plain Conditions
    (delta detection, tool-attribution) keep working."""
    out: list[Condition] = []
    for item in items or []:
        if isinstance(item, AnyOf):
            out.extend(item.conditions)
        else:
            out.append(item)
    return out


def evaluate_conditions(
    rule: "SetupRule",
    slice_df,
    registry: dict,
) -> tuple[bool, dict[str, dict]]:
    """
    Evaluate all conditions for rule against slice_df (df.iloc[:i+1]).

    Each detector is called at most once per bar (cached by name).
    Returns (all_passed, {detector_name: result_dict}).

    If a detector is not in the registry or returns insufficient_data,
    all conditions on it evaluate to False.
    """
    return evaluate_conditions_on_slice(rule.conditions, slice_df, registry)


def evaluate_conditions_on_slice(
    conditions: list[Condition],
    slice_df,
    registry: dict,
    ref_cache: dict[str, dict] | None = None,
    call_cache: dict[tuple, dict] | None = None,
) -> tuple[bool, dict[str, dict]]:
    """
    Evaluate a list of Conditions against slice_df.

    Each detector is called at most once per distinct kwargs set.
    Returns (all_passed, {detector_name: result_dict}).

    `ref_cache` holds the higher-timeframe signal-bar results, so an LTF entry
    condition can compare itself against the level that produced the signal
    (`value_ref="signal:..."`).

    `call_cache` lets the CALLER share detector results across several
    evaluations of the same slice. The engine evaluates invalidation and entry
    conditions separately on every LTF bar, and both ask detect_bos the same
    question with the same kwargs — without a shared cache that work is done
    twice, and detect_bos is ~80% of a backtest's runtime.
    """
    # slice_df may be None in unit tests whose detectors ignore it entirely.
    now_ts = (
        slice_df.index[-1]
        if slice_df is not None and len(slice_df)
        else None
    )

    cache: dict[str, dict] = {}
    # Keyed by (detector, kwargs) — NOT by detector alone. Two conditions on the
    # same detector with different params are two different questions; caching
    # on the name only answered the second with the first one's result, silently.
    # Same bug class as the P0-9 registry cache key.
    by_call: dict[tuple, dict] = call_cache if call_cache is not None else {}

    for cond in conditions:
        if isinstance(cond, AnyOf):
            passed = False
            for sub in cond.conditions:
                ok, sub_cache = evaluate_conditions_on_slice(
                    [sub], slice_df, registry, ref_cache, by_call
                )
                cache.update({k: v for k, v in sub_cache.items() if k not in cache})
                if ok:
                    passed = True
                    break
            if not passed:
                return False, cache
            continue

        det_name = cond.detector
        call_key = (det_name, json.dumps(cond.kwargs, sort_keys=True, default=str))

        # Fetch or reuse cached result
        if call_key not in by_call:
            fn = registry.get(det_name)
            if fn is None:
                return False, cache
            try:
                result = fn(slice_df, **cond.kwargs)
            except Exception:
                logger.exception("Detector %r raised an exception (treated as False)", det_name)
                return False, cache
            by_call[call_key] = result
            # The returned cache stays keyed by name for downstream consumers
            # (SL/TP resolution); the first call for a detector wins there.
            cache.setdefault(det_name, result)

        result = by_call[call_key]

        # Treat insufficient_data as a failed condition (not an error)
        if isinstance(result, dict) and result.get("status") == "insufficient_data":
            return False, cache

        if cond.value_ref is not None:
            expected = _resolve_value_ref(
                cond.value_ref, self_cache=by_call, named_cache=cache,
                ref_cache=ref_cache, slice_df=slice_df, registry=registry,
            )
            if expected is _MISSING:
                return False, cache
            if not _check_op(_get_field(result, cond.field), cond.op, expected, now_ts):
                return False, cache
        elif not cond.evaluate(result, now_ts):
            return False, cache

    return True, cache


def _resolve_value_ref(
    ref: str,
    self_cache: dict,
    named_cache: dict,
    ref_cache: dict | None,
    slice_df,
    registry: dict,
) -> Any:
    """Resolve "namespace:detector.field.path" to a value, or _MISSING."""
    try:
        namespace, rest = ref.split(":", 1)
        detector, path = rest.split(".", 1)
    except ValueError:
        return _MISSING

    if namespace == "signal":
        source = (ref_cache or {}).get(detector)
        if source is None:
            return _MISSING
        return _get_field(source, path)

    # "self": same slice. Reuse a result already computed for this evaluation;
    # otherwise call the detector with default params.
    source = named_cache.get(detector)
    if source is None:
        fn = registry.get(detector)
        if fn is None:
            return _MISSING
        try:
            source = fn(slice_df)
        except Exception:
            logger.exception("Detector %r raised while resolving value_ref", detector)
            return _MISSING
        named_cache.setdefault(detector, source)
        self_cache.setdefault((detector, "{}"), source)
    return _get_field(source, path)


# ---------------------------------------------------------------------------
# Detector registry (auto-discovered, excludes delta/no-df tools)
# ---------------------------------------------------------------------------

def build_detector_registry(include_delta: bool = False) -> dict[str, Any]:
    """
    Auto-discover all detector functions from copilot.detectors.*.
    Excludes no-df tools always. Excludes delta-only tools unless include_delta=True.
    Returns {function_name: callable}.
    """
    registry: dict[str, Any] = {}
    for module_info in pkgutil.iter_modules(_detectors_pkg.__path__):
        mod = importlib.import_module(f"copilot.detectors.{module_info.name}")
        for attr in dir(mod):
            if (attr.startswith("detect_") or attr.startswith("check_")) and callable(
                getattr(mod, attr)
            ):
                if attr in _NO_DF:
                    continue
                if attr in _DELTA_ONLY and not include_delta:
                    continue
                registry[attr] = getattr(mod, attr)
    return registry


# ---------------------------------------------------------------------------
# Built-in rules
# ---------------------------------------------------------------------------

BUILTIN_RULES: dict[str, SetupRule] = {
    # ── Rule 1: FVG + OB confluence long ────────────────────────────────────
    # Classic ICT model: bullish market structure, BOS confirmed, unmitigated
    # bullish OB below + fresh bullish FVG → enter on retrace to FVG midpoint.
    "fvg_ob_long": SetupRule(
        name="fvg_ob_long",
        direction="long",
        conditions=[
            Condition("detect_market_structure", "state", "eq", "bullish"),
            Condition("detect_bos", "count", "gt", 0),
            Condition("detect_bos", "latest_bias", "eq", "bullish"),
            Condition("detect_fvg", "count_active", "gt", 0),
            Condition("detect_fvg", "fvgs.0.type", "eq", "bullish"),
            Condition("detect_fvg", "fvgs.0.fill_state", "in", ["untouched", "IOFED"]),
            Condition("detect_order_block", "obs.0.type", "eq", "bullish"),
            Condition("detect_order_block", "obs.0.is_mitigated", "false"),
        ],
        entry_after="fvg_ce",
        sl_logic="ob",
        tp_logic="liquidity",
        required_session=None,
        required_killzone=None,
    ),

    # ── Rule 2: Liquidity sweep + BOS long (1h3m model) ─────────────────────
    # Sellside liquidity swept → bullish BOS with meaningful displacement →
    # fresh bullish FVG in the displacement → retrace entry.
    "sweep_bos_long": SetupRule(
        name="sweep_bos_long",
        direction="long",
        conditions=[
            Condition("detect_market_structure", "state", "eq", "bullish"),
            Condition("detect_liquidity", "recent_sweeps", "exists"),
            Condition("detect_liquidity", "recent_sweeps.0.side", "eq", "sellside"),
            Condition("detect_bos", "latest_bias", "eq", "bullish"),
            Condition("detect_bos", "count", "gt", 0),
            Condition("detect_bos", "events.0.break_candle_body_atr", "gte", 0.8),
            Condition("detect_fvg", "count_active", "gt", 0),
            Condition("detect_fvg", "fvgs.0.type", "eq", "bullish"),
        ],
        entry_after="fvg_ce",
        sl_logic="swing",
        tp_logic="rr:2.0",
        required_session=["london_open", "ny_am", "ny_pm"],
        required_killzone=None,
    ),

    # ── Rule 3: OB + FVG confluence short (bearish mirror) ──────────────────
    "ob_fvg_short": SetupRule(
        name="ob_fvg_short",
        direction="short",
        conditions=[
            Condition("detect_market_structure", "state", "eq", "bearish"),
            Condition("detect_liquidity", "recent_sweeps.0.side", "eq", "buyside"),
            Condition("detect_bos", "latest_bias", "eq", "bearish"),
            Condition("detect_bos", "count", "gt", 0),
            Condition("detect_fvg", "count_active", "gt", 0),
            Condition("detect_fvg", "fvgs.0.type", "eq", "bearish"),
            Condition("detect_fvg", "fvgs.0.fill_state", "in", ["untouched", "IOFED"]),
            Condition("detect_order_block", "obs.0.type", "eq", "bearish"),
            Condition("detect_order_block", "obs.0.is_mitigated", "false"),
        ],
        entry_after="fvg_ce",
        sl_logic="ob",
        tp_logic="liquidity",
        required_session=None,
        required_killzone=None,
    ),
}
