"""copilot.stats — statistics aggregation over journal records."""

from copilot.stats.aggregator import (
    StatsRow,
    ToolEffectivenessRow,
    compute_stats,
    print_stats,
    print_tool_effectiveness,
    tool_effectiveness,
)

__all__ = [
    "StatsRow",
    "ToolEffectivenessRow",
    "compute_stats",
    "print_stats",
    "print_tool_effectiveness",
    "tool_effectiveness",
]
