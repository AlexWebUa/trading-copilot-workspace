"""
Interactive REPL entry point.

Usage:
    python -m copilot
    python -m copilot --symbol ETHUSDT
    python -m copilot --symbol BTCUSDT --verbose

REPL commands:
    analyze [query]       — run a full analysis (default: "full analysis")
    switch <SYMBOL>       — change active symbol
    model <name>          — change LLM model
    verbose               — toggle verbose tool logging
    history               — show last 10 saved reports
    read <N>              — read report #N from history list
    session               — show current session config
    help                  — show this help
    exit / quit           — exit the REPL
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _check_api_key() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print(
            "Error: ANTHROPIC_API_KEY not set. "
            "Copy .env.example to .env and add your key.",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    _check_api_key()

    parser = argparse.ArgumentParser(description="Trading Co-Pilot REPL")
    parser.add_argument("--symbol", default=None, help="Starting symbol (e.g. BTCUSDT)")
    parser.add_argument("--model", default=None, help="Claude model ID")
    parser.add_argument("--verbose", action="store_true", help="Show tool calls")
    args = parser.parse_args()

    # Lazy imports (keep startup fast)
    from copilot.session import Session
    from copilot.llm.agent import TradingAgent
    from copilot.llm.report import list_recent_reports, read_report
    from copilot.detectors.sessions import current_killzone

    session = Session.load()
    if args.symbol:
        session.symbol = args.symbol.upper()
    if args.model:
        session.model = args.model
    if args.verbose:
        session.verbose = True

    agent = TradingAgent(
        symbol=session.symbol,
        model=session.model,
    )

    ctx = current_killzone()
    print(f"\n Trading Co-Pilot")
    print(f" Symbol : {session.symbol}")
    print(f" Model  : {session.model}")
    print(f" Time   : {ctx['kyiv_time']} Kyiv ({ctx['weekday']})")
    kz = ctx.get("active_killzone") or ctx.get("next_killzone", "—")
    print(f" KZ     : {kz}")
    print(f" OTT    : {'ACTIVE' if ctx['in_ott_window'] else 'inactive'}")
    print('\n Type "analyze" to start, "help" for commands.\n')

    while True:
        try:
            raw = input(f"[{agent.symbol}] >>> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            session.save()
            break

        if not raw:
            continue

        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if cmd in ("exit", "quit"):
            print("Bye.")
            session.save()
            break

        elif cmd == "help":
            print(__doc__)

        elif cmd == "session":
            print(f"  symbol   : {session.symbol}")
            print(f"  model    : {session.model}")
            print(f"  verbose  : {session.verbose}")

        elif cmd == "verbose":
            session.verbose = not session.verbose
            print(f"  verbose: {session.verbose}")

        elif cmd == "switch":
            if not rest:
                print("  Usage: switch <SYMBOL>")
            else:
                new_sym = rest.upper()
                session.symbol = new_sym
                agent = TradingAgent(symbol=new_sym, model=session.model)
                print(f"  Switched to {new_sym}. Conversation reset.")

        elif cmd == "model":
            if not rest:
                print(f"  Current model: {session.model}")
            else:
                session.model = rest.strip()
                agent = TradingAgent(symbol=session.symbol, model=session.model)
                print(f"  Model set to {session.model}. Conversation reset.")

        elif cmd == "history":
            reports = list_recent_reports(10)
            if not reports:
                print("  No saved reports yet.")
            else:
                for i, p in enumerate(reports, 1):
                    print(f"  {i:2}. {p.name}")

        elif cmd == "read":
            reports = list_recent_reports(10)
            try:
                n = int(rest) - 1
                if 0 <= n < len(reports):
                    print(read_report(reports[n]))
                else:
                    print(f"  No report #{n + 1}.")
            except (ValueError, IndexError):
                print("  Usage: read <N>")

        elif cmd == "analyze":
            query = rest or "Perform a full multi-timeframe market analysis."
            print(f"\n  Analyzing {agent.symbol}...\n")
            try:
                result = agent.analyze(query, verbose=session.verbose)
                session.last_report = result
                print(result)
                print()
            except Exception as e:
                print(f"  Error: {e}", file=sys.stderr)

        else:
            # Treat any unrecognised input as an analyze query (chat mode)
            print(f"\n  Analyzing...\n")
            try:
                result = agent.follow_up(raw, verbose=session.verbose)
                session.last_report = result
                print(result)
                print()
            except Exception as e:
                print(f"  Error: {e}", file=sys.stderr)

    session.save()


if __name__ == "__main__":
    main()
