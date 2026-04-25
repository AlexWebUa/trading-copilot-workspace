"""
Backtest engine — bar-by-bar historical simulation using the detector library.

Public API:
    SetupRule, Condition, BUILTIN_RULES        — rule definition
    ORDERFLOW_RULES, ORDERFLOW_GROUPS          — Phase 6 orderflow rules
    BacktestEngine, BacktestSummary            — engine and result
    simulated_exit, resolve_sl, resolve_tp     — simulation primitives
    print_summary, write_summary_to_journal    — reporting
    ComparisonRow, compare_rules, walk_forward — comparison runner
    AblationRow, ablate_conditions             — condition importance
    print_comparison, print_ablation           — table output
"""

from copilot.backtest.rules import (
    Condition,
    RuleConfigError,
    SetupRule,
    BUILTIN_RULES,
    evaluate_conditions,
    build_detector_registry,
)
from copilot.backtest.rules_orderflow import ORDERFLOW_RULES, ORDERFLOW_GROUPS
from copilot.backtest.simulate import (
    simulated_exit,
    resolve_entry,
    resolve_sl,
    resolve_tp,
)
from copilot.backtest.engine import BacktestEngine, BacktestSummary, _needs_delta
from copilot.backtest.report import (
    trades_to_summary,
    print_summary,
    write_summary_to_journal,
)
from copilot.backtest.compare import (
    ComparisonRow,
    AblationRow,
    compare_rules,
    walk_forward,
    ablate_conditions,
    print_comparison,
    print_ablation,
)

__all__ = [
    "Condition",
    "RuleConfigError",
    "SetupRule",
    "BUILTIN_RULES",
    "ORDERFLOW_RULES",
    "ORDERFLOW_GROUPS",
    "evaluate_conditions",
    "build_detector_registry",
    "simulated_exit",
    "resolve_entry",
    "resolve_sl",
    "resolve_tp",
    "BacktestEngine",
    "BacktestSummary",
    "_needs_delta",
    "trades_to_summary",
    "print_summary",
    "write_summary_to_journal",
    "ComparisonRow",
    "AblationRow",
    "compare_rules",
    "walk_forward",
    "ablate_conditions",
    "print_comparison",
    "print_ablation",
]
