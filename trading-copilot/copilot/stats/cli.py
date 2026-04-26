"""
CLI handler for the `stats` REPL command — imported by copilot/cli.py.

Usage examples:
  stats --group setup
  stats --group tool
  stats --group session
  stats --group dow
  stats --type backtest
  stats --type trade
  stats --setup sweep_bos_long --group session
  stats --compare live backtest
  stats --tool-effectiveness
"""

from __future__ import annotations

import argparse
import shlex
from pathlib import Path


def _do_stats(rest: str, journal_path: Path | None = None) -> None:
    """Parse `rest` string and execute the stats command."""
    parser = argparse.ArgumentParser(prog="stats", add_help=False, exit_on_error=False)
    parser.add_argument("--group", default="setup",
                        choices=["setup", "tool", "session", "dow", "account", "record_type"],
                        help="Dimension to group by")
    parser.add_argument("--type", dest="record_type", default=None,
                        choices=["trade", "backtest"],
                        help="Filter by record_type")
    parser.add_argument("--setup", default=None,
                        help="Filter to a specific setup name")
    parser.add_argument("--compare", nargs=2, metavar=("A", "B"),
                        help="Compare two record_types side by side")
    parser.add_argument("--tool-effectiveness", action="store_true",
                        help="Show winrate delta for each tool in tools_confirmed")
    parser.add_argument("--min-trades", type=int, default=5,
                        help="Minimum trades to mark row as sufficient (default: 5)")
    parser.add_argument("-h", "--help", action="store_true")

    try:
        args = parser.parse_args(shlex.split(rest) if rest.strip() else [])
    except (SystemExit, Exception) as e:
        print(f"stats: {e}")
        print("Usage: stats [--group setup|tool|session|dow|account|record_type]")
        print("             [--type trade|backtest] [--setup NAME]")
        print("             [--compare A B] [--tool-effectiveness] [--min-trades N]")
        return

    if args.help:
        parser.print_help()
        return

    from copilot.stats.aggregator import (
        compute_stats,
        print_stats,
        print_tool_effectiveness,
        tool_effectiveness,
    )

    if args.tool_effectiveness:
        rows = tool_effectiveness(path=journal_path)
        print_tool_effectiveness(rows)
        return

    if args.compare:
        type_a, type_b = args.compare
        rows_a = compute_stats(
            path=journal_path,
            group_by=args.group,
            record_type=type_a,
            setup_name=args.setup,
            min_trades=args.min_trades,
        )
        rows_b = compute_stats(
            path=journal_path,
            group_by=args.group,
            record_type=type_b,
            setup_name=args.setup,
            min_trades=args.min_trades,
        )
        print_stats(rows_a, group_by=f"{args.group} ({type_a})")
        print_stats(rows_b, group_by=f"{args.group} ({type_b})")
        return

    rows = compute_stats(
        path=journal_path,
        group_by=args.group,
        record_type=args.record_type,
        setup_name=args.setup,
        min_trades=args.min_trades,
    )
    print_stats(rows, group_by=args.group)
