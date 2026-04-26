"""Tests for copilot/backtest/rules_orderflow.py"""

from __future__ import annotations

import pytest

from copilot.backtest.engine import _needs_delta
from copilot.backtest.rules import BUILTIN_RULES, SetupRule
from copilot.backtest.rules_orderflow import ORDERFLOW_GROUPS, ORDERFLOW_RULES


# ---------------------------------------------------------------------------
# Validity
# ---------------------------------------------------------------------------

def test_all_orderflow_rules_valid():
    """All ORDERFLOW_RULES pass SetupRule.validate() without raising."""
    for name, rule in ORDERFLOW_RULES.items():
        rule.validate()  # should not raise


def test_group_a_uses_vp_detectors():
    """Every Group A rule must reference at least one check_* VP detector."""
    vp_detectors = {"check_ob_in_hvn", "check_poc_location", "check_price_in_lvn"}
    for name in ORDERFLOW_GROUPS["A"]:
        rule = ORDERFLOW_RULES[name]
        detectors = {c.detector for c in rule.conditions}
        assert detectors & vp_detectors, (
            f"{name}: Group A rule has no VP (check_*) condition. Detectors: {detectors}"
        )


def test_group_b_uses_cd_or_composite():
    """Every Group B rule must reference detect_cumulative_delta or check_cd_absorption."""
    cd_detectors = {"detect_cumulative_delta", "check_cd_absorption"}
    for name in ORDERFLOW_GROUPS["B"]:
        rule = ORDERFLOW_RULES[name]
        detectors = {c.detector for c in rule.conditions}
        assert detectors & cd_detectors, (
            f"{name}: Group B rule has no CD detector. Detectors: {detectors}"
        )


def test_sweep_cd_rule_has_delta_detector():
    """sweep_cd_manipulation_long must have detect_cumulative_delta as a condition."""
    rule = ORDERFLOW_RULES["sweep_cd_manipulation_long"]
    detectors = [c.detector for c in rule.conditions]
    assert "detect_cumulative_delta" in detectors


def test_needs_delta_detection():
    """
    _needs_delta() returns True for rules with detect_cumulative_delta,
    False for pure VP rules.
    """
    cd_rule = ORDERFLOW_RULES["sweep_cd_manipulation_long"]
    assert _needs_delta(cd_rule) is True

    vp_rule = ORDERFLOW_RULES["ob_in_hvn_long"]
    assert _needs_delta(vp_rule) is False

    builtin_rule = BUILTIN_RULES["fvg_ob_long"]
    assert _needs_delta(builtin_rule) is False


def test_rules_roundtrip():
    """All ORDERFLOW_RULES survive to_dict() → from_dict() round-trip."""
    for name, rule in ORDERFLOW_RULES.items():
        d = rule.to_dict()
        restored = SetupRule.from_dict(d)
        assert restored.name == rule.name, f"{name}: name mismatch after roundtrip"
        assert restored.direction == rule.direction, f"{name}: direction mismatch"
        assert len(restored.conditions) == len(rule.conditions), (
            f"{name}: condition count mismatch ({len(restored.conditions)} vs {len(rule.conditions)})"
        )
        assert restored.entry_after == rule.entry_after, f"{name}: entry_after mismatch"
        assert restored.sl_logic == rule.sl_logic, f"{name}: sl_logic mismatch"
        assert restored.tp_logic == rule.tp_logic, f"{name}: tp_logic mismatch"


def test_group_c_has_session_filter():
    """Every Group C rule must have a required_session filter set."""
    for name in ORDERFLOW_GROUPS["C"]:
        rule = ORDERFLOW_RULES[name]
        assert rule.required_session is not None and len(rule.required_session) > 0, (
            f"{name}: Group C rule has no required_session filter"
        )


def test_orderflow_rules_distinct_from_builtin():
    """ORDERFLOW_RULES keys must not overlap with BUILTIN_RULES keys."""
    overlap = set(ORDERFLOW_RULES.keys()) & set(BUILTIN_RULES.keys())
    assert len(overlap) == 0, f"Name collision between orderflow and builtin rules: {overlap}"


def test_orderflow_groups_cover_all_rules():
    """Every rule in ORDERFLOW_RULES must appear in exactly one group."""
    covered = set()
    for group_names in ORDERFLOW_GROUPS.values():
        for name in group_names:
            assert name not in covered, f"{name} appears in multiple groups"
            covered.add(name)

    all_names = set(ORDERFLOW_RULES.keys())
    uncovered = all_names - covered
    assert not uncovered, f"Rules not in any group: {uncovered}"
