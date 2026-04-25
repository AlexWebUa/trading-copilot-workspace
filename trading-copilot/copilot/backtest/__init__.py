"""
Backtest engine — bar-by-bar historical simulation using the detector library.

Public API:
    SetupRule, Condition, BUILTIN_RULES   — rule definition
    BacktestEngine, BacktestSummary       — engine and result
    simulated_exit, resolve_sl, resolve_tp — simulation primitives
    print_summary, write_summary_to_journal — reporting
"""

from copilot.backtest.rules import (
    Condition,
    RuleConfigError,
    SetupRule,
    BUILTIN_RULES,
    evaluate_conditions,
    build_detector_registry,
)
from copilot.backtest.simulate import (
    simulated_exit,
    resolve_entry,
    resolve_sl,
    resolve_tp,
)
from copilot.backtest.engine import BacktestEngine, BacktestSummary
from copilot.backtest.report import (
    trades_to_summary,
    print_summary,
    write_summary_to_journal,
)

__all__ = [
    "Condition",
    "RuleConfigError",
    "SetupRule",
    "BUILTIN_RULES",
    "evaluate_conditions",
    "build_detector_registry",
    "simulated_exit",
    "resolve_entry",
    "resolve_sl",
    "resolve_tp",
    "BacktestEngine",
    "BacktestSummary",
    "trades_to_summary",
    "print_summary",
    "write_summary_to_journal",
]
