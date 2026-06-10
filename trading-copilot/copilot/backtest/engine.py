"""
BacktestEngine — bar-by-bar historical simulation.

Core guarantee: strict look-ahead prevention.
  - Every detector call receives df.iloc[:i+1] — only bars up to and
    including bar i. Never bar i+1 or later.
  - Entry price is computed from bar i+1 onward (next_open) or from
    bar i's close (signal_close). SL/TP are set from bar i's window.
  - Exit simulation scans bars after the entry bar.

One position at a time — the engine does not pyramid or overlap.

State machine:
  _IDLE        → conditions pass → _SIGNAL (no LTF) or _LTF_SCAN (LTF)
  _SIGNAL      → entry resolved → _IN_TRADE
  _LTF_SCAN    → LTF entry conditions pass → _IN_TRADE
  _IN_TRADE    → SL/TP1 hit → _IDLE or _IN_TRADE_P2 (if tp_levels)
  _IN_TRADE_P2 → SL/TP2 hit → _IDLE
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

from copilot.backtest.rules import (
    SetupRule,
    evaluate_conditions,
    evaluate_conditions_on_slice,
    build_detector_registry,
)
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

# Detectors that require buy_vol/sell_vol/delta columns — triggers delta fetch
_DELTA_DETECTORS = frozenset({"detect_cumulative_delta"})


def _needs_delta(rule: SetupRule) -> bool:
    """Return True if any condition in rule references a delta-only detector."""
    all_conds = (
        list(rule.conditions)
        + list(rule.htf_conditions)
        + list(rule.entry_conditions)
    )
    return any(c.detector in _DELTA_DETECTORS for c in all_conds)


# Timeframe → minutes lookup
_TF_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15,
    "1h": 60, "4h": 240, "1d": 1440,
}

# Engine states
_IDLE = "IDLE"
_SIGNAL = "SIGNAL"
_IN_TRADE = "IN_TRADE"
_LTF_SCAN = "LTF_SCAN"
_IN_TRADE_P2 = "IN_TRADE_P2"


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
    # Change 6: variable risk reporting
    risk_pct: float = 1.0
    pnl_pct_series: list[float] = field(default_factory=list)
    total_pnl_pct: float = 0.0
    monthly_pnl_pct: float = 0.0

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "trades"}
        return d


@dataclass
class WalkForwardSummary:
    in_sample: BacktestSummary
    out_of_sample: BacktestSummary
    split_ratio: float
    split_bar_index: int

    def to_dict(self) -> dict:
        return {
            "split_ratio": self.split_ratio,
            "split_bar_index": self.split_bar_index,
            "in_sample": self.in_sample.to_dict(),
            "out_of_sample": self.out_of_sample.to_dict(),
        }


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
        walkforward_split: float | None = None,
    ) -> "BacktestSummary | WalkForwardSummary":
        """
        Run the bar-by-bar backtest.

        If walkforward_split is provided (0 < split < 1), splits the data into
        in-sample (first split%) and out-of-sample (remaining) periods and
        returns a WalkForwardSummary with metrics for both.
        """
        rule.validate()
        symbol = symbol.upper()

        df = self._fetch_data(symbol, tf, bars, start, end, rule=rule)
        if df.empty:
            return self._empty_summary(str(uuid.uuid4()), symbol, tf, rule, df)

        # Rebuild registry with delta detectors when the rule needs them
        if _needs_delta(rule):
            active_registry = build_detector_registry(include_delta=True)
        else:
            active_registry = self._registry

        if walkforward_split is not None:
            split_i = max(_MIN_LEADING_BARS + 5, int(len(df) * walkforward_split))
            is_df = df.iloc[:split_i].copy()
            oos_df = df.iloc[split_i:].copy()
            run_id = str(uuid.uuid4())
            is_summary = self._run_loop(
                is_df, rule, symbol, tf, active_registry, run_id, write_journal
            )
            oos_summary = self._run_loop(
                oos_df, rule, symbol, tf, active_registry, run_id, write_journal=False
            )
            return WalkForwardSummary(
                in_sample=is_summary,
                out_of_sample=oos_summary,
                split_ratio=walkforward_split,
                split_bar_index=split_i,
            )

        return self._run_loop(
            df, rule, symbol, tf, active_registry, str(uuid.uuid4()), write_journal
        )

    def _run_loop(
        self,
        df: pd.DataFrame,
        rule: SetupRule,
        symbol: str,
        tf: str,
        active_registry: dict,
        run_id: str,
        write_journal: bool,
    ) -> "BacktestSummary":
        """Core bar-by-bar simulation loop on a pre-fetched DataFrame slice."""
        min_i = _MIN_LEADING_BARS
        if len(df) <= min_i + 5:
            print(
                f"WARNING: insufficient data — need at least {min_i + 5} bars,"
                f" got {len(df)}. No trades evaluated."
            )
            return self._empty_summary(run_id, symbol, tf, rule, df)

        # === Change 1: Pre-fetch HTF data ===
        htf_dfs: dict[str, pd.DataFrame] = {}
        _htf_cache: dict[tuple, dict] = {}
        if rule.htf_conditions:
            tf_min = _TF_MINUTES.get(tf, 60)
            htf_tfs = {cond.htf_tf for cond in rule.htf_conditions}
            for htf_tf in htf_tfs:
                htf_min = _TF_MINUTES.get(htf_tf, 240)
                htf_bars = max(100, len(df) * tf_min // max(htf_min, 1) + 50)
                # Fetch by the backtest's own date range, not "most recent N
                # bars" — otherwise historical runs evaluate HTF conditions on
                # data from outside the backtest window. Leading buffer covers
                # detector lookback on the first evaluated bars.
                htf_start = df.index[0] - pd.Timedelta(minutes=htf_min * 150)
                htf_end = df.index[-1] + pd.Timedelta(minutes=tf_min)
                try:
                    try:
                        htf_dfs[htf_tf] = self._source.get_ohlc(
                            symbol, htf_tf,
                            start_time=htf_start.isoformat(),
                            end_time=htf_end.isoformat(),
                        )
                    except TypeError:
                        # Source doesn't support range fetch (e.g. test mocks)
                        htf_dfs[htf_tf] = self._source.get_ohlc(symbol, htf_tf, htf_bars)
                except Exception:
                    logger.warning("HTF data unavailable for %s/%s: HTF conditions will fail", symbol, htf_tf, exc_info=True)

        # === Change 2: Pre-fetch LTF data ===
        _ltf_df: pd.DataFrame | None = None
        if rule.entry_tf:
            tf_min = _TF_MINUTES.get(tf, 60)
            ltf_min = _TF_MINUTES.get(rule.entry_tf, 5)
            if ltf_min < tf_min:
                ltf_multiplier = tf_min // ltf_min
                ltf_bars_needed = len(df) * ltf_multiplier + 500
                try:
                    from copilot.data.binance import BinanceSource, fetch_ohlcv_batched
                    if isinstance(self._source, BinanceSource):
                        # Batched fetch handles >1500-bar requests and applies the
                        # 100k cap with a user-visible warning if exceeded.
                        _ltf_df = fetch_ohlcv_batched(
                            symbol, rule.entry_tf, ltf_bars_needed,
                            market=self._source._market,
                        )
                    else:
                        # Mock / non-Binance source (e.g. tests): delegate to get_ohlc
                        _ltf_df = self._source.get_ohlc(
                            symbol, rule.entry_tf, ltf_bars_needed
                        )
                except Exception:
                    logger.warning("LTF data unavailable for %s/%s: LTF entry will be skipped", symbol, rule.entry_tf, exc_info=True)
                    _ltf_df = None

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

        # LTF scan variables (Change 2)
        signal_bar_ts: pd.Timestamp | None = None
        ltf_scan_start_idx: int = 0
        ltf_scan_cursor: int = 0
        active_ltf_cursor: int = 0  # shared for IN_TRADE + IN_TRADE_P2 LTF exit

        # Partial TP variables (Change 3)
        active_original_sl: float | None = None
        current_sl_price: float | None = None
        current_tp2_price: float | None = None

        for i in range(min_i, len(df)):
            slice_df = df.iloc[: i + 1]

            # ── IN_TRADE_P2: second leg after TP1 ────────────────────────
            if state == _IN_TRADE_P2 and active_trade is not None:
                if current_sl_price is None:
                    raise RuntimeError("current_sl_price is None in _IN_TRADE_P2 state — state machine invariant violated")
                if current_tp2_price is None:
                    raise RuntimeError("current_tp2_price is None in _IN_TRADE_P2 state — state machine invariant violated")

                # Change 4: time-based exit
                bars_elapsed = i - active_entry_bar
                if rule.max_bars_open and bars_elapsed >= rule.max_bars_open:
                    ep = float(df.iloc[i]["close"])
                    et = df.index[i].strftime("%Y-%m-%dT%H:%M:%SZ")
                    remaining = 1.0 - sum(e["size_pct"] for e in active_trade.partial_exits)
                    pnl_e = compute_rr(active_trade.entry_price, active_original_sl, ep, rule.direction)  # type: ignore
                    active_trade.partial_exits.append({
                        "size_pct": remaining, "exit_price": ep,
                        "exit_ts": et, "pnl_r": pnl_e or 0.0,
                    })
                    active_trade = _finalize_trade(active_trade, "expired", ep, et,
                                                    rule.fee_bps, active_original_sl,
                                                    rule.slippage_bps)
                    bars_in_trade_list.append(bars_elapsed)
                    completed_trades.append(active_trade)
                    active_trade = None
                    active_original_sl = None
                    state = _IDLE
                    continue

                if rule.entry_tf and _ltf_df is not None:
                    # LTF exit for P2
                    current_htf_ts = df.index[i]
                    while active_ltf_cursor < len(_ltf_df):
                        active_ltf_cursor += 1
                        if active_ltf_cursor >= len(_ltf_df):
                            break
                        if _ltf_df.index[active_ltf_cursor] > current_htf_ts:
                            break
                        r2, ep2, et2 = simulated_exit(
                            direction=rule.direction,
                            entry_price=active_trade.entry_price,  # type: ignore
                            sl_price=current_sl_price,
                            tp_price=current_tp2_price,
                            future_bars=_ltf_df.iloc[active_ltf_cursor: active_ltf_cursor + 1],
                        )
                        if r2 is not None:
                            remaining = 1.0 - sum(e["size_pct"] for e in active_trade.partial_exits)
                            pnl_e = compute_rr(active_trade.entry_price, active_original_sl, ep2, rule.direction)  # type: ignore
                            active_trade.partial_exits.append({
                                "size_pct": remaining, "exit_price": ep2,
                                "exit_ts": et2, "pnl_r": pnl_e or 0.0,
                            })
                            active_trade = _finalize_trade(active_trade, r2, ep2, et2,
                                                            rule.fee_bps, active_original_sl,
                                                    rule.slippage_bps)
                            bars_in_trade_list.append(i - active_entry_bar)
                            completed_trades.append(active_trade)
                            active_trade = None
                            active_original_sl = None
                            state = _IDLE
                            break
                    continue
                else:
                    # HTF exit for P2
                    r2, ep2, et2 = simulated_exit(
                        direction=rule.direction,
                        entry_price=active_trade.entry_price,  # type: ignore
                        sl_price=current_sl_price,
                        tp_price=current_tp2_price,
                        future_bars=df.iloc[i: i + 1],
                    )
                    if r2 is not None:
                        remaining = 1.0 - sum(e["size_pct"] for e in active_trade.partial_exits)
                        pnl_e = compute_rr(active_trade.entry_price, active_original_sl, ep2, rule.direction)  # type: ignore
                        active_trade.partial_exits.append({
                            "size_pct": remaining, "exit_price": ep2,
                            "exit_ts": et2, "pnl_r": pnl_e or 0.0,
                        })
                        active_trade = _finalize_trade(active_trade, r2, ep2, et2,
                                                        rule.fee_bps, active_original_sl,
                                                    rule.slippage_bps)
                        bars_in_trade_list.append(i - active_entry_bar)
                        completed_trades.append(active_trade)
                        active_trade = None
                        active_original_sl = None
                        state = _IDLE
                    continue

            # ── IN_TRADE: check for exit on this bar ──────────────────────
            if state == _IN_TRADE and active_trade is not None:
                # Change 4: time-based exit
                bars_elapsed = i - active_entry_bar
                if rule.max_bars_open and bars_elapsed >= rule.max_bars_open:
                    ep = float(df.iloc[i]["close"])
                    et = df.index[i].strftime("%Y-%m-%dT%H:%M:%SZ")
                    active_trade = _finalize_trade(active_trade, "expired", ep, et,
                                                    rule.fee_bps, active_original_sl,
                                                    rule.slippage_bps)
                    bars_in_trade_list.append(bars_elapsed)
                    completed_trades.append(active_trade)
                    active_trade = None
                    active_original_sl = None
                    state = _IDLE
                    continue

                # Change 3: determine which TP to target
                tp1_price = active_trade.tp_prices[0] if active_trade.tp_prices else 0.0
                use_partial_tp = bool(rule.tp_levels) and len(rule.tp_levels) >= 2

                if rule.entry_tf and _ltf_df is not None:
                    # Change 2: LTF exit simulation
                    current_htf_ts = df.index[i]
                    while active_ltf_cursor < len(_ltf_df):
                        active_ltf_cursor += 1
                        if active_ltf_cursor >= len(_ltf_df):
                            break
                        if _ltf_df.index[active_ltf_cursor] > current_htf_ts:
                            break
                        result, exit_price, exit_ts = simulated_exit(
                            direction=rule.direction,
                            entry_price=active_trade.entry_price,  # type: ignore
                            sl_price=active_trade.sl_price,  # type: ignore
                            tp_price=tp1_price,
                            future_bars=_ltf_df.iloc[active_ltf_cursor: active_ltf_cursor + 1],
                        )
                        if result is not None:
                            if result == "win" and use_partial_tp:
                                # Change 3: TP1 hit → record partial, → P2
                                current_sl_price, current_tp2_price = _transition_to_p2(
                                    active_trade, rule, exit_price, exit_ts,
                                    df.iloc[:i + 1], signal_cache, active_original_sl,
                                )
                                active_trade.sl_price = current_sl_price  # type: ignore
                                active_ltf_cursor_p2 = active_ltf_cursor  # noqa: F841
                                state = _IN_TRADE_P2
                            else:
                                active_trade = _finalize_trade(
                                    active_trade, result, exit_price, exit_ts,
                                    rule.fee_bps, active_original_sl,
                                    rule.slippage_bps,
                                )
                                bars_in_trade_list.append(i - active_entry_bar)
                                completed_trades.append(active_trade)
                                active_trade = None
                                active_original_sl = None
                                state = _IDLE
                            break
                    continue

                else:
                    # Original HTF exit
                    result, exit_price, exit_ts = simulated_exit(
                        direction=rule.direction,
                        entry_price=active_trade.entry_price,  # type: ignore
                        sl_price=active_trade.sl_price,  # type: ignore
                        tp_price=tp1_price,
                        future_bars=df.iloc[i: i + 1],
                    )
                    if result is not None:
                        if result == "win" and use_partial_tp:
                            # Change 3: TP1 hit → record partial, → P2
                            current_sl_price, current_tp2_price = _transition_to_p2(
                                active_trade, rule, exit_price, exit_ts,
                                df.iloc[:i + 1], signal_cache, active_original_sl,
                            )
                            active_trade.sl_price = current_sl_price  # type: ignore
                            state = _IN_TRADE_P2
                        else:
                            active_trade = _finalize_trade(
                                active_trade, result, exit_price, exit_ts,
                                rule.fee_bps, active_original_sl,
                                rule.slippage_bps,
                            )
                            bars_in_trade_list.append(i - active_entry_bar)
                            completed_trades.append(active_trade)
                            active_trade = None
                            active_original_sl = None
                            state = _IDLE
                    continue

            # ── LTF_SCAN: wait for LTF entry confirmation ─────────────────
            if state == _LTF_SCAN:
                if _ltf_df is None:
                    skipped_entry += 1
                    state = _IDLE
                    continue

                current_htf_ts = df.index[i]
                while (
                    ltf_scan_cursor < len(_ltf_df)
                    and _ltf_df.index[ltf_scan_cursor] <= current_htf_ts
                ):
                    ltf_bars_elapsed = ltf_scan_cursor - ltf_scan_start_idx

                    # Timeout check
                    if ltf_bars_elapsed >= rule.max_entry_wait_bars_ltf:
                        skipped_entry += 1
                        state = _IDLE
                        break

                    ltf_slice = _ltf_df.iloc[: ltf_scan_cursor + 1]

                    # Evaluate LTF entry conditions
                    if rule.entry_conditions:
                        ok, _ = evaluate_conditions_on_slice(
                            rule.entry_conditions, ltf_slice, active_registry
                        )
                    else:
                        ok = True

                    if ok:
                        ltf_bar = _ltf_df.iloc[ltf_scan_cursor]
                        if rule.entry_after_ltf == "signal_close":
                            entry_price = float(ltf_bar["close"])
                        else:  # next_open
                            if ltf_scan_cursor + 1 < len(_ltf_df):
                                entry_price = float(_ltf_df.iloc[ltf_scan_cursor + 1]["open"])
                            else:
                                skipped_entry += 1
                                state = _IDLE
                                break

                        sl_price = resolve_sl(
                            rule.sl_logic, entry_price, rule.direction,
                            df.iloc[: i + 1], signal_cache,
                        )
                        tp1_price = _resolve_first_tp(rule, entry_price, sl_price,
                                                       df.iloc[: i + 1], signal_cache)
                        rr = compute_rr(entry_price, sl_price, tp1_price, rule.direction)
                        if rr is None or rr < 1.0:
                            skipped_rr += 1
                            state = _IDLE
                            break

                        entry_ts = _ltf_df.index[ltf_scan_cursor].strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )
                        session = session_from_ts(entry_ts)
                        dow = _ltf_df.index[ltf_scan_cursor].weekday()

                        active_trade = _make_trade_record(
                            run_id=run_id, rule=rule, symbol=symbol,
                            entry_price=entry_price, sl_price=sl_price,
                            tp_price=tp1_price, rr_planned=rr,
                            entry_ts=entry_ts, session=session,
                            day_of_week=dow,
                            tools_confirmed=_confirmed_tools(rule, include_ltf=True),
                        )
                        active_ltf_cursor = ltf_scan_cursor
                        active_entry_bar = i
                        active_original_sl = sl_price
                        state = _IN_TRADE
                        break

                    ltf_scan_cursor += 1
                continue  # always skip to next HTF bar after LTF_SCAN processing

            # ── SIGNAL: resolve entry price ───────────────────────────────
            if state == _SIGNAL:
                ep = resolve_entry(
                    entry_after=rule.entry_after,
                    signal_bar_idx=signal_i,
                    current_bar_idx=i,
                    df=df,
                    detector_cache=signal_cache,
                    direction=rule.direction,
                )
                if ep is _WAITING:
                    continue
                if ep is None:
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
                tp1_price = _resolve_first_tp(
                    rule, entry_price, sl_price,
                    df.iloc[: signal_i + 1], signal_cache,
                )
                rr = compute_rr(entry_price, sl_price, tp1_price, rule.direction)
                if rr is None or rr < 1.0:
                    skipped_rr += 1
                    state = _IDLE
                    continue

                entry_ts = df.index[i].strftime("%Y-%m-%dT%H:%M:%SZ")
                session = session_from_ts(entry_ts)
                dow = df.index[i].weekday()

                active_trade = _make_trade_record(
                    run_id=run_id, rule=rule, symbol=symbol,
                    entry_price=entry_price, sl_price=sl_price,
                    tp_price=tp1_price, rr_planned=rr,
                    entry_ts=entry_ts, session=session,
                    day_of_week=dow,
                    tools_confirmed=_confirmed_tools(rule),
                )
                active_entry_bar = i
                active_original_sl = sl_price
                state = _IN_TRADE
                continue

            # ── IDLE: evaluate conditions ──────────────────────────────────
            if state == _IDLE:
                ok, cache = evaluate_conditions(rule, slice_df, active_registry)
                if not ok:
                    continue

                # Session filter
                bar_ts = df.index[i].strftime("%Y-%m-%dT%H:%M:%SZ")
                if rule.required_session:
                    sess = session_from_ts(bar_ts)
                    if sess not in rule.required_session:
                        continue

                # Change 1: HTF condition evaluation
                if rule.htf_conditions:
                    htf_ok = _evaluate_htf_conditions(
                        rule.htf_conditions, htf_dfs, df.index[i],
                        active_registry, _htf_cache,
                        tf_minutes=_TF_MINUTES.get(tf, 60),
                    )
                    if not htf_ok:
                        continue

                # Signal fired
                total_signals += 1
                signal_cache = cache

                if rule.entry_tf and _ltf_df is not None:
                    # Change 2: transition to LTF_SCAN
                    # Scan starts at the signal bar's CLOSE — LTF bars inside
                    # the still-forming signal bar happened before the signal
                    # existed and must not be used for entry (look-ahead).
                    signal_bar_ts = df.index[i]
                    signal_close_ts = signal_bar_ts + pd.Timedelta(
                        minutes=_TF_MINUTES.get(tf, 60)
                    )
                    ltf_scan_start_idx = _find_ltf_idx(_ltf_df, signal_close_ts)
                    ltf_scan_cursor = ltf_scan_start_idx
                    signal_i = i
                    state = _LTF_SCAN
                else:
                    # Original path: go to SIGNAL
                    signal_i = i
                    state = _SIGNAL

        # Handle open trade at end of data
        if active_trade is not None and state in (_IN_TRADE, _IN_TRADE_P2):
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
            risk_pct=rule.risk_pct,
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
        rule: "SetupRule | None" = None,
    ) -> pd.DataFrame:
        # Determine how many bars we need
        if start is None and end is None:
            bars_needed = bars
        else:
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

        # Decide fetch method: delta-enriched or plain OHLCV
        use_delta = rule is not None and _needs_delta(rule)
        if use_delta:
            try:
                # P0-6: prefer the injected source (cache + mockable in tests)
                if hasattr(self._source, "get_ohlc_with_delta"):
                    df = self._source.get_ohlc_with_delta(symbol, tf, bars_needed)
                else:
                    from copilot.data.binance import fetch_ohlcv_with_delta
                    df = fetch_ohlcv_with_delta(symbol, tf, bars_needed, market="futures")
            except Exception:
                df = self._source.get_ohlc(symbol, tf, bars_needed)
        else:
            df = self._source.get_ohlc(symbol, tf, bars_needed)

        # Trim to date range
        if start is not None or (start is None and end is not None):
            start_dt = _parse_date(start) if start else None
            end_dt = _parse_date(end) if end else datetime.now(timezone.utc)
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
            risk_pct=rule.risk_pct,
        )


# ---------------------------------------------------------------------------
# Private helpers (module-level)
# ---------------------------------------------------------------------------

def _resolve_first_tp(
    rule: SetupRule,
    entry_price: float,
    sl_price: float,
    slice_df,
    cache: dict,
) -> float:
    """Resolve TP1 — from tp_levels[0] if present, else tp_logic."""
    if rule.tp_levels:
        return resolve_tp(
            rule.tp_levels[0].logic, entry_price, sl_price,
            rule.direction, slice_df, cache,
        )
    return resolve_tp(
        rule.tp_logic, entry_price, sl_price,
        rule.direction, slice_df, cache,
    )


def _transition_to_p2(
    trade: TradeRecord,
    rule: SetupRule,
    tp1_exit_price: float,
    tp1_exit_ts: str,
    slice_df,
    cache: dict,
    original_sl: float | None,
) -> tuple[float, float]:
    """
    Record TP1 partial exit on trade and compute new SL + TP2 prices.
    Returns (new_sl_price, tp2_price).
    """
    tp1_level = rule.tp_levels[0]
    pnl_r_tp1 = compute_rr(
        trade.entry_price, original_sl or trade.sl_price,  # type: ignore
        tp1_exit_price, rule.direction,
    )
    trade.partial_exits.append({
        "size_pct": tp1_level.size_pct,
        "exit_price": tp1_exit_price,
        "exit_ts": tp1_exit_ts,
        "pnl_r": pnl_r_tp1 or 0.0,
    })

    # Resolve new SL after TP1
    if rule.sl_after_tp1 == "be":
        new_sl = float(trade.entry_price)  # type: ignore
    elif rule.sl_after_tp1 and rule.sl_after_tp1.startswith("atr:"):
        new_sl = resolve_sl(
            rule.sl_after_tp1, tp1_exit_price, rule.direction, slice_df, cache
        )
    else:
        new_sl = float(trade.sl_price)  # type: ignore  keep original

    # Resolve TP2 — use original SL for risk reference (RR-based TP2 shouldn't
    # shrink because SL moved to BE; it should still be 3R from original risk)
    tp2_logic = rule.tp_levels[1].logic
    tp2_risk_sl = original_sl if original_sl is not None else float(trade.sl_price)  # type: ignore
    tp2_price = resolve_tp(
        tp2_logic, float(trade.entry_price), tp2_risk_sl, rule.direction, slice_df, cache  # type: ignore
    )
    trade.tp_prices.append(tp2_price)

    return new_sl, tp2_price


def _evaluate_htf_conditions(
    htf_conditions,
    htf_dfs: dict,
    current_bar_ts,
    registry: dict,
    htf_cache: dict,
    tf_minutes: int = 60,
) -> bool:
    """Evaluate all HTF conditions. Returns True only if all pass.

    The decision moment is the current base-TF bar's CLOSE. Only HTF bars
    whose own close is at or before that moment may be seen — the forming
    HTF bar would repaint (look-ahead).
    """
    current_bar_close = current_bar_ts + pd.Timedelta(minutes=tf_minutes)
    for htf_cond in htf_conditions:
        htf_df = htf_dfs.get(htf_cond.htf_tf)
        if htf_df is None:
            return False
        htf_minutes = _TF_MINUTES.get(htf_cond.htf_tf, 240)
        htf_closes = htf_df.index + pd.Timedelta(minutes=htf_minutes)
        htf_slice = htf_df[htf_closes <= current_bar_close]
        if htf_slice.empty:
            return False
        htf_bar_idx = len(htf_slice) - 1
        cache_key = (
            htf_cond.htf_tf,
            htf_cond.detector,
            htf_bar_idx,
            repr(sorted(htf_cond.kwargs.items())),
        )
        if cache_key not in htf_cache:
            fn = registry.get(htf_cond.detector)
            if fn is None:
                return False
            try:
                htf_cache[cache_key] = fn(htf_slice, **htf_cond.kwargs)
            except Exception:
                return False
        htf_result = htf_cache[cache_key]
        if isinstance(htf_result, dict) and htf_result.get("status") == "insufficient_data":
            return False
        if not htf_cond.evaluate(htf_result):
            return False
    return True


def _find_ltf_idx(ltf_df: pd.DataFrame, cutoff_ts) -> int:
    """Return index of first LTF bar opening at or after cutoff_ts.

    cutoff_ts is the signal bar's close — the earliest moment the signal
    can be acted on.
    """
    mask = ltf_df.index >= cutoff_ts
    if mask.any():
        return int(mask.argmax())
    return len(ltf_df)


def _confirmed_tools(rule: SetupRule, include_ltf: bool = False) -> list[str]:
    """Detectors whose conditions actually gated this entry (P0-6).

    Previously this recorded signal_cache keys, which also contained
    detectors called as SL/TP utilities (e.g. volume profile pulled in by
    TP resolution) — polluting tool-effectiveness stats. Only condition
    detectors belong here: base + HTF, plus LTF entry conditions when the
    entry came through the LTF scan.
    """
    detectors = [c.detector for c in rule.conditions]
    detectors += [c.detector for c in rule.htf_conditions]
    if include_ltf:
        detectors += [c.detector for c in rule.entry_conditions]
    seen: list[str] = []
    for d in detectors:
        if d not in seen:
            seen.append(d)
    return seen


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
    fee_bps: float = 0.0,
    original_sl: float | None = None,
    slippage_bps: float = 0.0,
) -> TradeRecord:
    trade.exit_price = exit_price
    trade.ts_exit = exit_ts

    if trade.partial_exits:
        # Weighted average pnl_r from all partial exits
        total_pnl_r = sum(e["pnl_r"] * e["size_pct"] for e in trade.partial_exits)
        trade.pnl_r = round(total_pnl_r, 4)
        if trade.pnl_r > 0.01:
            trade.result = "win"
        elif trade.pnl_r < -0.01:
            trade.result = "loss"
        else:
            trade.result = "be"
    else:
        trade.result = result
        if exit_price is not None and trade.entry_price and trade.sl_price:
            trade.pnl_r = compute_rr(
                trade.entry_price, trade.sl_price, exit_price, trade.direction
            )

    # Change 5 / P0-6: apply cost model (uses original risk distance).
    # fee_bps and slippage_bps are PER SIDE — charged on entry notional and
    # on exit notional (size-weighted across partial exits).
    effective_sl = original_sl if original_sl is not None else trade.sl_price
    cost_bps = (fee_bps or 0.0) + (slippage_bps or 0.0)
    if cost_bps and trade.pnl_r is not None and trade.entry_price and effective_sl:
        risk = abs(trade.entry_price - effective_sl)
        if risk > 0:
            if trade.partial_exits:
                exit_notional = sum(
                    e["size_pct"] * e["exit_price"] for e in trade.partial_exits
                )
            else:
                exit_notional = exit_price if exit_price is not None else trade.entry_price
            cost_r = ((trade.entry_price + exit_notional) * cost_bps / 10_000) / risk
            trade.pnl_r = round(trade.pnl_r - cost_r, 4)

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
