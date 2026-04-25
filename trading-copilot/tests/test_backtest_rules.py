"""Tests for copilot/backtest/rules.py"""

from __future__ import annotations

import pytest

from copilot.backtest.rules import (
    BUILTIN_RULES,
    Condition,
    RuleConfigError,
    SetupRule,
    _MISSING,
    _check_op,
    _get_field,
    evaluate_conditions,
)


# ---------------------------------------------------------------------------
# _get_field — dotted path navigation
# ---------------------------------------------------------------------------

def test_get_field_simple_key():
    assert _get_field({"state": "bullish"}, "state") == "bullish"


def test_get_field_nested_dict():
    assert _get_field({"a": {"b": 42}}, "a.b") == 42


def test_get_field_nested_list_index():
    result = {"fvgs": [{"type": "bullish"}]}
    assert _get_field(result, "fvgs.0.type") == "bullish"


def test_get_field_out_of_bounds_returns_missing():
    result = {"fvgs": [{"type": "bullish"}]}
    assert _get_field(result, "fvgs.5.type") is _MISSING


def test_get_field_missing_key_returns_missing():
    assert _get_field({"state": "bullish"}, "nonexistent") is _MISSING


def test_get_field_deeply_missing_returns_missing():
    assert _get_field({}, "a.b.c.d") is _MISSING


def test_get_field_none_value_returned():
    # None is a valid field value, distinct from _MISSING
    assert _get_field({"key": None}, "key") is None


# ---------------------------------------------------------------------------
# _check_op — operator evaluation
# ---------------------------------------------------------------------------

def test_check_op_eq_match():
    assert _check_op("bullish", "eq", "bullish") is True


def test_check_op_eq_no_match():
    assert _check_op("bearish", "eq", "bullish") is False


def test_check_op_ne():
    assert _check_op("bullish", "ne", "bearish") is True


def test_check_op_gt_lt():
    assert _check_op(5, "gt", 3) is True
    assert _check_op(5, "lt", 3) is False
    assert _check_op(5, "gte", 5) is True
    assert _check_op(5, "lte", 5) is True


def test_check_op_in_list():
    assert _check_op("bullish", "in", ["bullish", "bearish"]) is True
    assert _check_op("neutral", "in", ["bullish", "bearish"]) is False


def test_check_op_not_in():
    assert _check_op("none", "not_in", ["BOS", "MSS"]) is True
    assert _check_op("BOS", "not_in", ["BOS", "MSS"]) is False


def test_check_op_missing_returns_false():
    assert _check_op(_MISSING, "eq", "bullish") is False
    assert _check_op(_MISSING, "gt", 0) is False
    assert _check_op(_MISSING, "in", ["x"]) is False


def test_check_op_exists():
    assert _check_op("anything", "exists", None) is True
    assert _check_op(None, "exists", None) is False
    assert _check_op(_MISSING, "exists", None) is False


def test_check_op_true_false():
    assert _check_op(True, "true", None) is True
    assert _check_op(False, "true", None) is False
    assert _check_op(False, "false", None) is True
    assert _check_op(True, "false", None) is False
    assert _check_op(_MISSING, "false", None) is True   # missing = falsy


# ---------------------------------------------------------------------------
# Condition.evaluate
# ---------------------------------------------------------------------------

def test_condition_evaluate_eq():
    c = Condition("detect_bos", "direction", "eq", "bullish")
    assert c.evaluate({"direction": "bullish"}) is True
    assert c.evaluate({"direction": "bearish"}) is False


def test_condition_evaluate_nested():
    c = Condition("detect_fvg", "fvgs.0.type", "eq", "bullish")
    assert c.evaluate({"fvgs": [{"type": "bullish"}]}) is True
    assert c.evaluate({"fvgs": []}) is False


def test_condition_invalid_op_raises():
    with pytest.raises(RuleConfigError):
        Condition("det", "field", "UNKNOWN_OP", None)


def test_condition_roundtrip():
    c = Condition("detect_fvg", "fvgs.0.fill_state", "in", ["untouched", "IOFED"], {"max_results": 3})
    restored = Condition.from_dict(c.to_dict())
    assert restored.detector == c.detector
    assert restored.field == c.field
    assert restored.op == c.op
    assert restored.value == c.value
    assert restored.kwargs == c.kwargs


# ---------------------------------------------------------------------------
# evaluate_conditions
# ---------------------------------------------------------------------------

def _mock_registry(returns: dict[str, dict]) -> dict:
    """Build a fake detector registry from a {name: result_dict} map."""
    return {name: (lambda *a, r=result, **k: r) for name, result in returns.items()}


def test_evaluate_conditions_all_pass():
    registry = _mock_registry({
        "detect_market_structure": {"state": "bullish"},
        "detect_bos": {"direction": "bullish", "type": "BOS"},
    })
    rule = SetupRule(
        name="test",
        direction="long",
        conditions=[
            Condition("detect_market_structure", "state", "eq", "bullish"),
            Condition("detect_bos", "direction", "eq", "bullish"),
        ],
        entry_after="next_open",
        sl_logic="atr:1.5",
        tp_logic="rr:2.0",
    )
    ok, cache = evaluate_conditions(rule, None, registry)
    assert ok is True
    assert "detect_market_structure" in cache
    assert "detect_bos" in cache


def test_evaluate_conditions_one_fails():
    registry = _mock_registry({
        "detect_market_structure": {"state": "bearish"},  # wrong
        "detect_bos": {"direction": "bullish"},
    })
    rule = SetupRule(
        name="test",
        direction="long",
        conditions=[
            Condition("detect_market_structure", "state", "eq", "bullish"),
            Condition("detect_bos", "direction", "eq", "bullish"),
        ],
        entry_after="next_open",
        sl_logic="atr:1.5",
        tp_logic="rr:2.0",
    )
    ok, _ = evaluate_conditions(rule, None, registry)
    assert ok is False


def test_evaluate_conditions_detector_called_once_per_bar():
    """Same detector referenced twice → called exactly once (cached)."""
    call_count = {"n": 0}

    def spy_detector(*args, **kwargs):
        call_count["n"] += 1
        return {"state": "bullish", "count": 5}

    registry = {"detect_market_structure": spy_detector}
    rule = SetupRule(
        name="test",
        direction="long",
        conditions=[
            Condition("detect_market_structure", "state", "eq", "bullish"),
            Condition("detect_market_structure", "count", "gt", 0),
        ],
        entry_after="next_open",
        sl_logic="atr:1.5",
        tp_logic="rr:2.0",
    )
    evaluate_conditions(rule, None, registry)
    assert call_count["n"] == 1


def test_evaluate_conditions_insufficient_data():
    registry = _mock_registry({
        "detect_fvg": {"status": "insufficient_data", "needed": 5, "got": 2},
    })
    rule = SetupRule(
        name="test",
        direction="long",
        conditions=[Condition("detect_fvg", "count_active", "gt", 0)],
        entry_after="next_open",
        sl_logic="atr:1.5",
        tp_logic="rr:2.0",
    )
    ok, _ = evaluate_conditions(rule, None, registry)
    assert ok is False


# ---------------------------------------------------------------------------
# BUILTIN_RULES
# ---------------------------------------------------------------------------

def test_builtin_rules_exist():
    assert "fvg_ob_long" in BUILTIN_RULES
    assert "sweep_bos_long" in BUILTIN_RULES
    assert "ob_fvg_short" in BUILTIN_RULES


def test_builtin_rules_valid():
    for name, rule in BUILTIN_RULES.items():
        assert rule.direction in ("long", "short"), f"{name}: bad direction"
        assert len(rule.conditions) > 0, f"{name}: no conditions"
        assert rule.entry_after, f"{name}: no entry_after"
        assert rule.sl_logic, f"{name}: no sl_logic"
        assert rule.tp_logic, f"{name}: no tp_logic"


def test_builtin_rules_roundtrip():
    for name, rule in BUILTIN_RULES.items():
        restored = SetupRule.from_dict(rule.to_dict())
        assert restored.name == rule.name
        assert restored.direction == rule.direction
        assert len(restored.conditions) == len(rule.conditions)
