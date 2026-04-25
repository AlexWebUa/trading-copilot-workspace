"""
Interactive REPL entry point.

Usage:
    python -m copilot
    python -m copilot --symbol ETHUSDT
    python -m copilot --symbol BTCUSDT --verbose

REPL commands:
    analyze [query]                        — run a full analysis
    switch <SYMBOL>                        — change active symbol
    model <name>                           — change LLM model
    verbose                                — toggle verbose tool logging
    history                                — show last 10 saved reports
    read <N>                               — read report #N from history list
    session                                — show current session config
    log                                    — record a new trade in the journal
    trades [--setup X] [--result Y]        — list journal entries
           [--symbol S] [--last N]
           [--account A] [--tag T]
    edit <id>                              — update exit/result for a trade
    help                                   — show this help
    exit / quit                            — exit the REPL
"""

from __future__ import annotations

import argparse
import shlex
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Journal helpers
# ---------------------------------------------------------------------------

def _ask(prompt: str, default: str = "") -> str:
    suffix = f" ({default})" if default else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val if val else default


def _ask_float(prompt: str) -> float | None:
    raw = input(f"  {prompt} (blank to skip): ").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        print("    Invalid number, skipped.")
        return None


def _ask_list(prompt: str) -> list[str]:
    raw = input(f"  {prompt} (comma-separated, blank to skip): ").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _ask_float_list(prompt: str) -> list[float]:
    raw = input(f"  {prompt} (comma-separated, blank to skip): ").strip()
    if not raw:
        return []
    result = []
    for x in raw.split(","):
        try:
            result.append(float(x.strip()))
        except ValueError:
            pass
    return result


def _do_log(default_symbol: str) -> None:
    from copilot.journal import (
        TradeRecord, append_record, compute_rr, session_from_ts, parse_ts
    )

    print("  ── New Trade Record ──")
    record_type = _ask("Type [trade/backtest]", "trade")
    symbol = _ask("Symbol", default_symbol).upper()
    account_type = _ask("Account [demo/phase1/phase2/live]", "demo")
    setup_name = _ask("Setup (e.g. 1h3m, silver_bullet)")
    direction = _ask("Direction [long/short]")
    ts_entry_raw = _ask("Entry time (ISO UTC or 'now')", "now")
    ts_entry = parse_ts(ts_entry_raw)

    entry_price = _ask_float("Entry price")
    sl_price = _ask_float("SL price")
    tp_prices = _ask_float_list("TP prices")
    htf_bias = _ask("HTF bias [bullish/bearish/ranging]", "")
    session = _ask(
        "Session [london_open/ny_am/ny_pm/asia/london/off_hours]",
        session_from_ts(ts_entry),
    )
    killzone = _ask("Killzone [09:00/15:00/17:00 or blank]", "")
    tools_confirmed = _ask_list("Tools confirmed (e.g. fvg,order_block)")
    tools_pending = _ask_list("Tools pending")
    notes = _ask("Notes", "")
    tags = _ask_list("Tags")
    result = _ask("Result [win/loss/be/pending/missed]", "pending")
    exit_price = _ask_float("Exit price") if result != "pending" else None

    # Auto-compute planned R:R from TP1
    rr_planned: float | None = None
    if entry_price and sl_price and tp_prices:
        rr_planned = compute_rr(entry_price, sl_price, tp_prices[0], direction)

    # Auto-compute pnl_r if exit known
    pnl_r: float | None = None
    if entry_price and sl_price and exit_price and direction:
        pnl_r = compute_rr(entry_price, sl_price, exit_price, direction)

    # day_of_week from ts_entry
    try:
        dt = datetime.fromisoformat(ts_entry.replace("Z", "+00:00"))
        day_of_week = dt.weekday()
    except ValueError:
        day_of_week = datetime.now(timezone.utc).weekday()

    rec = TradeRecord(
        symbol=symbol,
        record_type=record_type,
        account_type=account_type,
        setup_name=setup_name,
        direction=direction,
        ts_entry=ts_entry,
        entry_price=entry_price,
        sl_price=sl_price,
        tp_prices=tp_prices,
        exit_price=exit_price,
        htf_bias=htf_bias,
        session=session or None,
        killzone=killzone or None,
        tools_confirmed=tools_confirmed,
        tools_pending=tools_pending,
        notes=notes,
        tags=tags,
        result=result,
        rr_planned=rr_planned,
        pnl_r=pnl_r,
        day_of_week=day_of_week,
    )
    append_record(rec)
    rr_str = f"  Planned R:R: {rr_planned}R to TP1" if rr_planned else ""
    print(f"\n  Saved → {rec.id[:8]} ({rec.setup_name} {rec.direction} {rec.symbol} {rec.result})")
    if rr_str:
        print(rr_str)


def _do_trades(rest: str) -> None:
    from copilot.journal import filter_by

    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parser.add_argument("--setup", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--result", default=None)
    parser.add_argument("--session", default=None)
    parser.add_argument("--account", dest="account_type", default=None)
    parser.add_argument("--tag", default=None)
    parser.add_argument("--last", type=int, default=20)
    try:
        args = parser.parse_args(shlex.split(rest) if rest else [])
    except (argparse.ArgumentError, SystemExit):
        print("  Usage: trades [--setup X] [--result Y] [--symbol S] [--last N] [--account A] [--tag T]")
        return

    records = filter_by(
        setup_name=args.setup,
        symbol=args.symbol,
        result=args.result,
        session=args.session,
        account_type=args.account_type,
        tag=args.tag,
        last=args.last,
    )

    if not records:
        print("  No records found.")
        return

    # Header
    cols = ["#", "ID", "Date", "Symbol", "Setup", "Dir", "Entry", "SL", "R:R", "Result", "PnL(R)", "Session"]
    widths = [3, 8, 10, 8, 16, 5, 10, 10, 5, 7, 7, 12]
    header = "  " + "  ".join(c.ljust(w) for c, w in zip(cols, widths))
    print(header)
    print("  " + "-" * (sum(widths) + 2 * len(widths)))

    for i, r in enumerate(records, 1):
        date = (r.ts_entry or r.ts_created)[:10]
        entry = f"{r.entry_price:.2f}" if r.entry_price else "—"
        sl = f"{r.sl_price:.2f}" if r.sl_price else "—"
        rr = f"{r.rr_planned}" if r.rr_planned else "—"
        pnl = f"{r.pnl_r:+.2f}" if r.pnl_r is not None else "—"
        row = [
            str(i), r.id[:8], date, r.symbol, r.setup_name,
            r.direction, entry, sl, rr, r.result, pnl, r.session or "—",
        ]
        print("  " + "  ".join(v.ljust(w) for v, w in zip(row, widths)))


def _do_edit(rest: str) -> None:
    from copilot.journal import get_by_id, update_record, compute_rr

    partial_id = rest.strip()
    if not partial_id:
        print("  Usage: edit <id-prefix>")
        return

    rec = get_by_id(partial_id)
    if not rec:
        print(f"  No record found matching '{partial_id}'.")
        return

    print(f"  Editing {rec.id[:8]} — {rec.setup_name} {rec.direction} {rec.symbol} → {rec.result}")

    updates: dict = {}

    exit_price_raw = input("  Exit price (blank to skip): ").strip()
    if exit_price_raw:
        try:
            updates["exit_price"] = float(exit_price_raw)
        except ValueError:
            print("    Invalid, skipped.")

    result_raw = input(f"  Result [win/loss/be/pending/missed] ({rec.result}): ").strip()
    if result_raw:
        updates["result"] = result_raw

    # Auto-compute pnl_r if exit_price is now known
    entry = rec.entry_price
    sl = rec.sl_price
    exit_p = updates.get("exit_price", rec.exit_price)
    direction = rec.direction
    if entry and sl and exit_p and direction:
        computed_pnl = compute_rr(entry, sl, exit_p, direction)
        pnl_raw = input(f"  PnL R-multiples (blank → auto {computed_pnl}R): ").strip()
        updates["pnl_r"] = float(pnl_raw) if pnl_raw else computed_pnl
    else:
        pnl_raw = input("  PnL R-multiples (blank to skip): ").strip()
        if pnl_raw:
            try:
                updates["pnl_r"] = float(pnl_raw)
            except ValueError:
                pass

    notes_raw = input("  Notes to append (blank to skip): ").strip()
    if notes_raw:
        existing = rec.notes or ""
        updates["notes"] = (existing + "\n" + notes_raw).strip()

    tags_raw = input("  Tags to add (comma-separated, blank to skip): ").strip()
    if tags_raw:
        new_tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        updates["tags"] = list(set(rec.tags) | set(new_tags))

    if not updates:
        print("  Nothing to update.")
        return

    update_record(rec.id, updates)
    print(f"  Updated {rec.id[:8]}.")


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

        elif cmd == "log":
            try:
                _do_log(session.symbol)
            except (KeyboardInterrupt, EOFError):
                print("\n  Cancelled.")

        elif cmd == "trades":
            _do_trades(rest)

        elif cmd == "edit":
            try:
                _do_edit(rest)
            except (KeyboardInterrupt, EOFError):
                print("\n  Cancelled.")

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
