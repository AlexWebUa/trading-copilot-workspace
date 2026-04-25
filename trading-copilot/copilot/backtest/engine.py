"""
BacktestEngine — bar-by-bar historical simulation.

Core guarantee: strict look-ahead prevention.
  - Every detector call receives df.iloc[:i+1] — only bars up to and
    including bar i. Never bar i+1 or later.
  - Entry price is computed from bar i+1 onward (next_open) or from
    bar i's close (signal_close). SL/TP are set from bar i's window.
  - Exit simulation scans bars after the entry bar.

One position at a time — the engine does not pyramid or overlap.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from copilot.backtest.rules import SetupRule, evaluate_conditions, build_detector_registry
from copilot.backtest.simulate import (
    _WAITING,
    simulated_exit,
    resolve_entry,
    resolve_sl,
    resolve_tp,
)
from copilot.journal.record import TradeRecord, compute_rr, session_from_ts

# Minimum bars before the engine starts evaluating signals
_MIN_LEADING_BARS = 50

# Timeframe → minutes lookup for date-range bar count estimation
_TF_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15,
    "1h": 60, "4h": 240, "1d": 1440,
}

# Engine states
_IDLE = "IDLE"
_SIGNAL = "SIGNAL"
_IN_TRADE = "IN_TRADE"


# ---------------------------------------------------------------------------
# BacktestSummary
# ---------------------------------------------------------------------------

@dataclass
class BacktestSummary:
    run_id: str
    symbol: str
    tf: str
    start: str
    end: str
    rule_name: str
    direction: str
    total_bars_scanned: int = 0
    total_signals: int = 0
    total_trades: int = 0
    skipped_rr: int = 0
    skipped_entry: int = 0
    wins: int = 0
    losses: int = 0
    breakevens: int = 0
    winrate: float = 0.0
    avg_winner_r: float = 0.0
    avg_loser_r: float = 0.0
    expectancy: float = 0.0
    profit_factor: float = 0.0
    max_consec_losses: int = 0
    avg_bars_in_trade: float = 0.0
    max_bars_in_trade: int = 0
    pnl_r_series: list[float] = field(default_factory=list)
    session_breakdown: dict[str, dict] = field(default_factory=dict)
    trades: list[TradeRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "trades"}
        return d


# ---------------------------------------------------------------------------
# BacktestEngine
# ---------------------------------------------------------------------------

class BacktestEngine:
    def __init__(
        self,
        source=None,
        journal_path: Path | None = None,
        detector_registry: dict | None = None,
    ):
        if source is None:
            from copilot.data.binance import BinanceSource
            source = BinanceSource()
        self._source = source
        self._journal_path = journal_path
        self._registry = detector_registry or build_detector_registry()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        symbol: str,
        tf: str,
        rule: SetupRule,
        bars: int = 1000,
        start: str | None = None,
        end: str | None = None,
        write_journal: bool = True,
    ) -> BacktestSummary:
        """
        Run the bar-by-bar backtest.

        Fetches OHLCV data, evaluates rule conditions bar-by-bar,
        simulates exits, writes TradeRecords to the journal (unless
        write_journal=False), and returns a BacktestSummary.
        """
        rule.validate()
        symbol = symbol.upper()

        df = self._fetch_data(symbol, tf, bars, start, end)
        if df.empty:
            return self._empty_summary(str(uuid.uuid4()), symbol, tf, rule, df)

        min_i = _MIN_LEADING_BARS
        if len(df) <= min_i + 5:
            print(
                f"WARNING: insufficient data — need at least {min_i + 5} bars,"
                f" got {len(df)}. No trades evaluated."
            )
            return self._empty_summary(str(uuid.uuid4()), symbol, tf, rule, df)

        run_id = str(uuid.uuid4())
        completed_trades: list[TradeRecord] = []

        # Counters
        total_signals = 0
        skipped_rr = 0
        skipped_entry = 0
        bars_in_trade_list: list[int] = []

        # State machine
        state = _IDLE
        signal_i = -1
        signal_cache: dict = {}
        active_trade: TradeRecord | None = None
        active_entry_bar: int = -1

        for i in range(min_i, len(df)):
            slice_df = df.iloc[: i + 1]  # strict look-ahead boundary

            # ── IN_TRADE: check for exit on this bar ──────────────────────
            if state == _IN_TRADE and active_trade is not None:
                result, exit_price, exit_ts = simulated_exit(
                    direction=rule.direction,
                    entry_price=active_trade.entry_price,  # type: ignore[arg-type]
                    sl_price=active_trade.sl_price,  # type: ignore[arg-type]
                    tp_price=active_trade.tp_prices[0] if active_trade.tp_prices else 0.0,
                    future_bars=df.iloc[i : i + 1],
                )
                if result is not None:
                    active_trade = _finalize_trade(
                        active_trade, result, exit_price, exit_ts
                    )
                    bars_in_trade_list.append(i - active_entry_bar)
                    completed_trades.append(active_trade)
                    active_trade = None
                    state = _IDLE
                continue  # skip signal eval on exit bar

            # ── SIGNAL: resolve entry price ───────────────────────────────
            if state == _SIGNAL:
                ep = resolve_entry(
                    entry_after=rule.entry_after,
                    signal_bar_idx=signal_i,
                    current_bar_idx=i,
                    df=df,
                    detector_cache=signal_cache,
                )
                if ep is _WAITING:
                    continue
                if ep is None:
                    # Cancelled (timeout or missing data)
                    skipped_entry += 1
                    state = _IDLE
                    continue

                entry_price = float(ep)
                sl_price = resolve_sl(
                    sl_logic=rule.sl_logic,
                    entry_price=entry_price,
                    direction=rule.direction,
                    slice_df=df.iloc[: signal_i + 1],
                    detector_cache=signal_cache,
                )
                tp_price = resolve_tp(
                    tp_logic=rule.tp_logic,
                    entry_price=entry_price,
                    sl_price=sl_price,
                    direction=rule.direction,
                    slice_df=df.iloc[: signal_i + 1],
                    detector_cache=signal_cache,
                )

                rr = compute_rr(entry_price, sl_price, tp_price, rule.direction)
                if rr is None or rr < 1.0:
                    skipped_rr += 1
                    state = _IDLE
                    continue

                entry_ts = df.index[i].strftime("%Y-%m-%dT%H:%M:%SZ")
                session = session_from_ts(entry_ts)
                dow = df.index[i].weekday()

                active_trade = _make_trade_record(
                    run_id=run_id,
                    rule=rule,
                    symbol=symbol,
                    entry_price=entry_price,
                    sl_price=sl_price,
                    tp_price=tp_price,
                    rr_planned=rr,
                    entry_ts=entry_ts,
                    session=session,
                    day_of_week=dow,
                    tools_confirmed=list(signal_cache.keys()),
                )
                active_entry_bar = i
                state = _IN_TRADE
                continue

            # ── IDLE: evaluate conditions ──────────────────────────────────
            if state == _IDLE:
                ok, cache = evaluate_conditions(rule, slice_df, self._registry)
                if not ok:
                    continue

                # Session filter
                bar_ts = df.index[i].strftime("%Y-%m-%dT%H:%M:%SZ")
                if rule.required_session:
                    sess = session_from_ts(bar_ts)
                    if sess not in rule.required_session:
                        continue

                # Signal fired
                total_signals += 1
                signal_i = i
                signal_cache = cache
                state = _SIGNAL

        # Handle open trade at end of data
        if active_trade is not None and state == _IN_TRADE:
            completed_trades.append(active_trade)  # result stays "pending"

        # Build summary
        start_ts = df.index[min_i].strftime("%Y-%m-%dT%H:%M:%SZ")
        end_ts = df.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ")

        from copilot.backtest.report import trades_to_summary, write_summary_to_journal

        summary = trades_to_summary(
            run_id=run_id,
            symbol=symbol,
            tf=tf,
            rule_name=rule.name,
            direction=rule.direction,
            start=start_ts,
            end=end_ts,
            total_bars=len(df) - min_i,
            total_signals=total_signals,
            skipped_rr=skipped_rr,
            skipped_entry=skipped_entry,
            bars_in_trade_list=bars_in_trade_list,
            trades=completed_trades,
        )
        summary.trades = completed_trades

        if write_journal and completed_trades:
            written = write_summary_to_journal(
                summary, completed_trades, path=self._journal_path
            )
            summary.total_trades = written if written > 0 else len(completed_trades)

        return summary

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_data(
        self,
        symbol: str,
        tf: str,
        bars: int,
        start: str | None,
        end: str | None,
    ) -> pd.DataFrame:
        if start is None and end is None:
            return self._source.get_ohlc(symbol, tf, bars)

        # Date-range fetch
        tf_min = _TF_MINUTES.get(tf, 60)
        start_dt = _parse_date(start) if start else None
        end_dt = _parse_date(end) if end else datetime.now(timezone.utc)

        if start_dt:
            total_min = (end_dt - start_dt).total_seconds() / 60
            bars_needed = min(int(total_min / tf_min) + 20, 5000)
        else:
            bars_needed = bars

        if bars_needed > 5000:
            print(f"WARNING: date range exceeds 5000 bars cap — truncating.")
            bars_needed = 5000

        df = self._source.get_ohlc(symbol, tf, bars_needed)

        # Trim to date range
        if start_dt:
            df = df[df.index >= pd.Timestamp(start_dt, tz="UTC")]
        if end_dt:
            df = df[df.index <= pd.Timestamp(end_dt, tz="UTC")]
        return df

    def _empty_summary(
        self,
        run_id: str,
        symbol: str,
        tf: str,
        rule: SetupRule,
        df: pd.DataFrame,
    ) -> BacktestSummary:
        start = df.index[0].strftime("%Y-%m-%dT%H:%M:%SZ") if not df.empty else "—"
        end = df.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ") if not df.empty else "—"
        return BacktestSummary(
            run_id=run_id,
            symbol=symbol,
            tf=tf,
            start=start,
            end=end,
            rule_name=rule.name,
            direction=rule.direction,
        )


# ---------------------------------------------------------------------------
# Private helpers (module-level)
# ---------------------------------------------------------------------------

def _make_trade_record(
    run_id: str,
    rule: SetupRule,
    symbol: str,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    rr_planned: float,
    entry_ts: str,
    session: str,
    day_of_week: int,
    tools_confirmed: list[str],
) -> TradeRecord:
    ts_created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return TradeRecord(
        record_type="backtest",
        ts_created=ts_created,
        symbol=symbol,
        account_type="backtest",
        setup_name=rule.name,
        direction=rule.direction,
        result="pending",
        entry_price=entry_price,
        sl_price=sl_price,
        tp_prices=[tp_price],
        rr_planned=rr_planned,
        ts_entry=entry_ts,
        session=session,
        day_of_week=day_of_week,
        tools_confirmed=tools_confirmed,
        tags=["backtest", f"run_id:{run_id}"],
        htf_bias="",
    )


def _finalize_trade(
    trade: TradeRecord,
    result: str,
    exit_price: float | None,
    exit_ts: str | None,
) -> TradeRecord:
    trade.result = result
    trade.exit_price = exit_price
    trade.ts_exit = exit_ts
    if exit_price and trade.entry_price and trade.sl_price:
        trade.pnl_r = compute_rr(
            trade.entry_price, trade.sl_price, exit_price, trade.direction
        )
    return trade


def _parse_date(s: str) -> datetime:
    """Parse ISO date string to UTC datetime."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {s!r}")
