"""
ORB Algo | Flux Charts — a bar-for-bar port of the public TradingView script.

Why a standalone simulator and not a `SetupRule`: the script resets per session,
counts retests of the range edge, exits on an EMA cross in three partial takes
and flattens at the next session. None of that is expressible in the rule DSL,
and bending the engine to fit one public indicator would cost more than this
file.

Two ways to run it, selected by `OrbParams`:

  faithful  every switch off. Reproduces the script INCLUDING the behaviours
            that flatter its dashboard, so the port can be calibrated against a
            real TradingView screenshot before anything else is trusted.
  honest    each switch fixes one of those behaviours, independently, so the
            contribution of each to the published "edge" can be measured:

    fill_at_close   a dynamic take-profit is triggered by the close crossing the
                    EMA, but the script books the fill AT THE EMA — a price the
                    bar has already left. Honest: fill at that close.
    stop_first      the script skips the stop on any bar that also produced a
                    take-profit. A resting stop fills intrabar, before a
                    close-based exit can be decided. Honest: stop wins.
    skip_entry_bar  entry is at the close, yet the same bar's high/low is
                    checked against the stop and targets — a range that
                    happened before the fill (the engine's P0-8 class).
    cost_bps        fee + slippage per side, charged on entry and exit notional.

Accounting is separate from the trade path. `dashboard()` reproduces the
script's own table, which takes `abs()` of a session-end exit and so books a
PROFITABLE end-of-session exit as a loss. `trades` carries signed P&L.

Pine execution order is preserved on purpose: the script's blocks are
sequential `if`s evaluated on every confirmed bar, so a bar can close the range,
register a breakout and take the entry all at once. Reordering them changes the
trades.

The trader's variant (2026-09-15) is off by default, so the calibrated script
stays untouched: `sl_method="Fractal"` puts the stop behind the last 3-candle
fractal confirmed before the session opened, `min_stop_atr` floors that stop,
`tp_method="FixedR"` takes the whole position at a fixed multiple of risk, and
`simulate(..., bias=...)` refuses breakouts against a higher-timeframe bias.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

_MIN_PROFIT_PCT = 0.20
_MIN_PROFIT_INCREMENT_PCT = 0.075
_ATR_TP_MULTS = (0.75, 1.5, 2.25)
_ATR_LENGTH = 12
_RETESTS_NEEDED = {"High": 0, "Medium": 1, "Low": 2, "Lowest": 3}
_NY = ZoneInfo("America/New_York")
_NS_PER_MIN = 60_000_000_000


@dataclass(frozen=True)
class OrbParams:
    # Session anchor. "utc0" is what `session.isfirstbar_regular` gives on
    # Binance crypto symbols (verified against the trader's 12-13 Sep 2026
    # screenshot). "ny_open" is 09:30 America/New_York, DST-aware — a TradingView
    # custom session typed in UTC would NOT follow DST and would open an hour
    # early from November to March.
    anchor: str = "utc0"
    orb_minutes: int = 30
    sensitivity: str = "Medium"
    breakout: str = "Close"                 # "Close" | "EMA"
    tp_method: str = "Dynamic"              # "Dynamic" | "ATR" | "FixedR"
    ema_length: int = 9
    sl_method: str = "Balanced"             # "Safer" | "Balanced" | "Risky" | "Fractal"
    adaptive_sl: bool = True
    exit_ratios: tuple[float, float, float] = (0.90, 0.05, 0.05)
    # Widen a stop that came out tighter than this many ATR(12). 0 = off, as in
    # the script. Same rule the trader chose for 30mOF: widen, and let the
    # target be recomputed from the wider stop.
    min_stop_atr: float = 0.0
    tp_r: float = 1.5                       # tp_method="FixedR": target = entry ± tp_r × risk

    fill_at_close: bool = False
    stop_first: bool = False
    skip_entry_bar: bool = False
    cost_bps: float = 0.0

    def honest(self, cost_bps: float = 6.0) -> "OrbParams":
        """Same strategy, every flattering behaviour fixed, costs charged."""
        from dataclasses import replace
        return replace(self, fill_at_close=True, stop_first=True,
                       skip_entry_bar=True, cost_bps=cost_bps)


@dataclass
class _Orb:
    start_i: int
    start_ns: int
    high: float = np.nan
    low: float = np.nan
    state: str = "range"                    # range | waiting | breakout | entry

    bo_bull: bool = False
    bo_start: int = -1
    bo_retests: int = 0

    entry_i: int | None = None
    entry_px: float = np.nan
    bull: bool = False
    entry_atr: float = np.nan
    sl_init: float = np.nan

    sl_px: float | None = None
    sl_i: int | None = None                 # -1 = closed by a target, as in the script
    exit_kind: str | None = None            # "sl" | "session" | "tp3" | "tp"
    tp_i: list = field(default_factory=lambda: [None, None, None])
    tp_trigger: list = field(default_factory=lambda: [None, None, None])
    tp_fill: list = field(default_factory=lambda: [None, None, None])


@dataclass
class OrbResult:
    params: OrbParams
    orbs: list
    trades: pd.DataFrame
    index: pd.DatetimeIndex


def _diff_pct(a: float, b: float) -> float:
    return abs(a - b) / b * 100.0


def _pine_ema(src: np.ndarray, length: int) -> np.ndarray:
    # Seed convention differs from Pine's by a vanishing amount: at alpha 0.2 a
    # seed error decays below 1e-5 within 50 bars, and the first session starts
    # hundreds of bars into any window this runs on.
    return pd.Series(src).ewm(span=length, adjust=False).mean().to_numpy()


def _pine_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    prev = np.concatenate(([np.nan], close[:-1]))
    tr = np.where(
        np.isnan(prev),
        high - low,
        np.maximum.reduce([high - low, np.abs(high - prev), np.abs(low - prev)]),
    )
    return pd.Series(tr).ewm(alpha=1.0 / length, adjust=False).mean().to_numpy()


def _session_starts(index: pd.DatetimeIndex, anchor: str) -> np.ndarray:
    index = index.as_unit("ns")
    ts = index.asi8
    day = index.normalize().asi8
    starts = np.zeros(len(index), dtype=bool)
    if anchor == "utc0":
        starts[1:] = day[1:] != day[:-1]
        return starts
    if anchor == "ny_open":
        uniq = np.unique(day)
        opens = np.array([
            pd.Timestamp(datetime.combine(
                pd.Timestamp(int(d), tz="UTC").date(), dtime(9, 30), tzinfo=_NY
            )).tz_convert("UTC").value
            for d in uniq
        ], dtype=np.int64)
        anchor_ns = opens[np.searchsorted(uniq, day)]
        starts[1:] = (ts[1:] >= anchor_ns[1:]) & (ts[:-1] < anchor_ns[1:])
        return starts
    raise ValueError(f"unknown anchor {anchor!r}")


def simulate(
    df: pd.DataFrame,
    params: OrbParams = OrbParams(),
    bias: np.ndarray | None = None,
) -> OrbResult:
    """Run the script over `df` (canonical OHLCV, UTC index, bars < 15m).

    `bias`, if given, is +1 / -1 / 0 per bar of `df` and may only reflect what
    was known by that bar's close (see `bias_series`). A breakout whose side
    disagrees with it is not traded; the session goes back to waiting, so a
    later breakout the other way can still be taken.
    """
    if params.sensitivity not in _RETESTS_NEEDED:
        raise ValueError(f"sensitivity {params.sensitivity!r}")
    need = _RETESTS_NEEDED[params.sensitivity]

    h = df["high"].to_numpy(np.float64)
    lo = df["low"].to_numpy(np.float64)
    c = df["close"].to_numpy(np.float64)
    # Nanoseconds explicitly: the data layer's index can be datetime64[ms], and
    # `asi8` then returns milliseconds — adding a 30-minute range in ns made
    # every opening range last 57 years and the first port produced no trades.
    ts = df.index.as_unit("ns").asi8
    ema = _pine_ema((h + lo) / 2.0, params.ema_length)
    atr = _pine_atr(h, lo, c, _ATR_LENGTH)
    starts = _session_starts(df.index, params.anchor)
    orb_len = params.orb_minutes * _NS_PER_MIN

    # 3-candle fractals by pivot bar, the strict definition `detect_order_flow`
    # uses. A pivot at j is usable only once bar j+1 has closed.
    frac_low = np.full(len(c), np.nan)
    frac_high = np.full(len(c), np.nan)
    if len(c) >= 3:
        is_fl = (lo[1:-1] < lo[:-2]) & (lo[1:-1] < lo[2:])
        is_fh = (h[1:-1] > h[:-2]) & (h[1:-1] > h[2:])
        frac_low[1:-1][is_fl] = lo[1:-1][is_fl]
        frac_high[1:-1][is_fh] = h[1:-1][is_fh]

    orbs: list[_Orb] = []
    cur: _Orb | None = None

    # Bar 0 is excluded by the script's `last_bar_index - bar_index < maxBarsBack`.
    for i in range(1, len(c)):
        if starts[i]:
            if cur is not None and cur.entry_i is not None and cur.sl_i is None:
                cur.sl_px = c[i - 1]
                cur.sl_i = i - 1
                cur.exit_kind = "session"
            cur = _Orb(start_i=i, start_ns=int(ts[i]))
            orbs.append(cur)

        if cur is None:
            continue

        # ── Opening range ─────────────────────────────────────────────────
        if cur.state == "range" and ts[i] < cur.start_ns + orb_len:
            cur.high = h[i] if np.isnan(cur.high) else max(cur.high, h[i])
            cur.low = lo[i] if np.isnan(cur.low) else min(cur.low, lo[i])
        if cur.state == "range" and ts[i] >= cur.start_ns + orb_len:
            cur.state = "waiting"

        # ── Breakout ──────────────────────────────────────────────────────
        if cur.state == "waiting":
            cp = ema[i] if params.breakout == "EMA" else c[i]
            if cp > cur.high or cp < cur.low:
                cur.bo_bull = bool(cp > cur.high)
                cur.bo_start = i
                cur.bo_retests = 0
                cur.state = "breakout"

        # ── Failed breakout / retest / entry — one block, no re-check of
        # state inside it, exactly as the script is written.
        if cur.state == "breakout":
            bull = cur.bo_bull
            if (bull and c[i] < cur.high) or (not bull and c[i] > cur.low):
                cur.state = "waiting"
            if i > cur.bo_start and (
                (bull and c[i] > cur.high and lo[i] < cur.high)
                or (not bull and c[i] < cur.low and h[i] > cur.low)
            ):
                cur.bo_retests += 1
            if cur.bo_retests >= need:
                sl = None
                if bias is None or bias[i] == (1 if bull else -1):
                    sl = _initial_stop(cur, bull, c[i], atr[i], frac_low, frac_high, params)
                if sl is None:
                    # Against the bias, or no fractal on the stop side: not a
                    # trade. Back to waiting rather than closing the session.
                    cur.state = "waiting"
                else:
                    cur.state = "entry"
                    cur.entry_atr = atr[i]
                    cur.entry_i = i
                    cur.entry_px = c[i]
                    cur.bull = bull
                    cur.sl_px = sl
                    cur.sl_init = sl

        # ── Manage the position ───────────────────────────────────────────
        if cur.state == "entry":
            if params.skip_entry_bar and i == cur.entry_i:
                continue
            if params.stop_first:
                _check_stop(cur, i, h, lo, exclude_tp_bars=False)
            _take_profits(cur, i, h, lo, c, ema, params)
            if not params.stop_first:
                _check_stop(cur, i, h, lo, exclude_tp_bars=True)

    return OrbResult(params, orbs, _trades(orbs, df.index, params), df.index)


def _initial_stop(orb: _Orb, bull: bool, entry: float, atr_i: float,
                  frac_low: np.ndarray, frac_high: np.ndarray,
                  p: OrbParams) -> float | None:
    center = (orb.high + orb.low) / 2.0
    if p.sl_method == "Safer":
        sl = (center + orb.high) / 2.0 if bull else (center + orb.low) / 2.0
    elif p.sl_method == "Balanced":
        sl = center
    elif p.sl_method == "Risky":
        sl = (center + orb.low) / 2.0 if bull else (center + orb.high) / 2.0
    elif p.sl_method == "Fractal":
        sl = _fractal_before_open(orb.start_i, bull, entry, frac_low, frac_high)
        if sl is None:
            return None
    else:
        raise ValueError(f"sl_method {p.sl_method!r}")
    if p.min_stop_atr > 0 and not np.isnan(atr_i):
        floor = p.min_stop_atr * atr_i
        if abs(entry - sl) < floor:
            sl = entry - floor if bull else entry + floor
    return sl


def _fractal_before_open(start_i: int, bull: bool, entry: float,
                         frac_low: np.ndarray, frac_high: np.ndarray) -> float | None:
    """The last 3-candle fractal confirmed before the session opened, on the
    stop side of the entry: a fractal low under a long, a high over a short.

    Confirmed before the open means the pivot's right-hand bar closed before the
    session's first bar, so j + 1 < start_i. Walking back past a fractal on the
    wrong side of the entry is deliberate — a stop above a long's entry is not
    a stop.
    """
    levels = frac_low if bull else frac_high
    for j in range(start_i - 2, 0, -1):
        lvl = levels[j]
        if np.isnan(lvl):
            continue
        if (bull and lvl < entry) or (not bull and lvl > entry):
            return float(lvl)
    return None


def bias_series(events: list, htf_minutes: int, index: pd.DatetimeIndex,
                bar_minutes: int = 5) -> np.ndarray:
    """+1 / -1 / 0 per bar of `index`: the direction of the last higher-timeframe
    structure event that was KNOWN by that bar's close.

    `events` are `detect_order_flow` events, oldest first. `break_ts` is the
    OPEN of the HTF candle whose body closed through the key, so the flip is
    known only at break_ts + htf_minutes. Releasing it at break_ts would hand
    every 5m bar inside that candle a close that had not happened yet.
    """
    out = np.zeros(len(index), dtype=np.int8)
    if not events:
        return out
    known = (pd.to_datetime([e["break_ts"] for e in events], utc=True)
             + pd.Timedelta(minutes=htf_minutes)).as_unit("ns").asi8
    sign = np.array([1 if e["direction"] == "bullish" else -1 for e in events], dtype=np.int8)
    closes = (index.as_unit("ns") + pd.Timedelta(minutes=bar_minutes)).asi8
    pos = np.searchsorted(known, closes, side="right") - 1
    ok = pos >= 0
    out[ok] = sign[pos[ok]]
    return out


def _ratios(p: OrbParams) -> tuple[float, float, float]:
    # A fixed-R target closes the whole position in one fill.
    return (1.0, 0.0, 0.0) if p.tp_method == "FixedR" else p.exit_ratios


def _check_stop(orb: _Orb, i: int, h, lo, exclude_tp_bars: bool) -> None:
    if orb.sl_px is None or orb.sl_i is not None:
        return
    hit = (orb.bull and lo[i] < orb.sl_px) or (not orb.bull and h[i] > orb.sl_px)
    if not hit:
        return
    if exclude_tp_bars and i in orb.tp_i:
        return
    orb.sl_i = i
    orb.exit_kind = "sl"


def _take_profits(orb: _Orb, i: int, h, lo, c, ema, p: OrbParams) -> None:
    bull = orb.bull
    entry = orb.entry_px

    if p.tp_method == "Dynamic":
        e = ema[i]
        profitable = (bull and e > entry) or (not bull and e < entry)
        if not (profitable and _diff_pct(e, entry) >= _MIN_PROFIT_PCT):
            return
        cross = (bull and c[i] < e) or (not bull and c[i] > e)
        fill = c[i] if p.fill_at_close else e
        t = orb.tp_trigger
        if orb.sl_i is None and orb.tp_i[0] is None and cross:
            _book(orb, 0, i, e, fill)
            if p.adaptive_sl:
                orb.sl_px = entry
        elif orb.sl_i is None and orb.tp_i[0] is not None and orb.tp_i[1] is None and cross:
            # Increments are judged on the TRIGGER level, which is what the
            # script compares against; only the booked fill changes in honest mode.
            if ((bull and e > t[0]) or (not bull and e < t[0])) and \
                    _diff_pct(e, t[0]) >= _MIN_PROFIT_INCREMENT_PCT:
                _book(orb, 1, i, e, fill)
        elif orb.sl_i is None and orb.tp_i[1] is not None and orb.tp_i[2] is None and cross:
            if ((bull and e > t[1]) or (not bull and e < t[1])) and \
                    _diff_pct(e, t[1]) >= _MIN_PROFIT_INCREMENT_PCT:
                _book(orb, 2, i, e, fill)
                orb.sl_i = -1
                orb.exit_kind = "tp3"
        return

    if p.tp_method == "ATR":
        sign = 1 if bull else -1
        levels = [entry + orb.entry_atr * m * sign for m in _ATR_TP_MULTS]

        def touched(level: float) -> bool:
            return (bull and h[i] >= level) or (not bull and lo[i] <= level)

        if orb.sl_i is None and orb.tp_i[0] is None and touched(levels[0]):
            _book(orb, 0, i, levels[0], levels[0])
            if p.adaptive_sl:
                orb.sl_px = entry
        elif orb.sl_i is None and orb.tp_i[0] is not None and orb.tp_i[1] is None \
                and touched(levels[1]):
            _book(orb, 1, i, levels[1], levels[1])
        elif orb.sl_i is None and orb.tp_i[1] is not None and orb.tp_i[2] is None \
                and touched(levels[2]):
            _book(orb, 2, i, levels[2], levels[2])
            orb.sl_i = -1
            orb.exit_kind = "tp3"
        return

    if p.tp_method == "FixedR":
        risk = abs(entry - orb.sl_init)
        level = entry + p.tp_r * risk if bull else entry - p.tp_r * risk
        hit = (bull and h[i] >= level) or (not bull and lo[i] <= level)
        if orb.sl_i is None and orb.tp_i[0] is None and hit:
            _book(orb, 0, i, level, level)
            orb.sl_i = -1
            orb.exit_kind = "tp"
        return

    raise ValueError(f"tp_method {p.tp_method!r}")


def _book(orb: _Orb, k: int, i: int, trigger: float, fill: float) -> None:
    orb.tp_i[k] = i
    orb.tp_trigger[k] = trigger
    orb.tp_fill[k] = fill


_TRADE_COLUMNS = [
    "orb_n", "session", "entry_ts", "side", "entry", "sl_init", "range_high",
    "range_low", "tp_hits", "exit_kind", "closed", "gross_pct", "net_pct",
    "risk_pct", "entry_atr", "r",
]


def _trades(orbs: list, index: pd.DatetimeIndex, p: OrbParams) -> pd.DataFrame:
    ratios = _ratios(p)
    rows = []
    for n, orb in enumerate(orbs):
        if orb.entry_i is None:
            continue
        closed = orb.sl_i is not None
        sign = 1.0 if orb.bull else -1.0
        entry = orb.entry_px
        gross = 0.0
        taken = 0.0
        exit_notional = 0.0
        for k in range(3):
            fill = orb.tp_fill[k]
            if fill is None:
                continue
            r = ratios[k]
            gross += r * sign * (fill - entry) / entry * 100.0
            exit_notional += r * fill / entry
            taken += r
        remaining = max(0.0, 1.0 - taken)
        if closed and orb.sl_i != -1 and remaining > 1e-12:
            gross += remaining * sign * (orb.sl_px - entry) / entry * 100.0
            exit_notional += remaining * orb.sl_px / entry
        cost = p.cost_bps / 100.0 * (1.0 + exit_notional) if closed else 0.0
        net = gross - cost
        risk_pct = abs(entry - orb.sl_init) / entry * 100.0
        rows.append({
            "orb_n": n,
            "session": index[orb.start_i],
            "entry_ts": index[orb.entry_i],
            "side": "long" if orb.bull else "short",
            "entry": entry,
            "sl_init": orb.sl_init,
            "range_high": orb.high,
            "range_low": orb.low,
            "tp_hits": sum(x is not None for x in orb.tp_fill),
            "exit_kind": orb.exit_kind,
            "closed": closed,
            "gross_pct": gross,
            "net_pct": net,
            "risk_pct": risk_pct,
            "entry_atr": orb.entry_atr,
            "r": net / risk_pct if risk_pct > 0 else np.nan,
        })
    return pd.DataFrame(rows, columns=_TRADE_COLUMNS)


def dashboard(result: OrbResult) -> dict:
    """The script's own "ORB Backtesting" table, bug for bug.

    Includes the `abs()` on the session-end exit, which turns a profitable exit
    into a subtracted loss. Use `result.trades` for signed P&L.
    """
    ratios = _ratios(result.params)
    total = 0.0
    wins = losses = 0
    for orb in result.orbs:
        if orb.entry_i is None:
            continue
        success = False
        taken = 0.0
        for k in range(3):
            if orb.tp_fill[k] is not None:
                success = True
                total += _diff_pct(orb.tp_fill[k], orb.entry_px) * ratios[k]
                taken += ratios[k]
        if orb.sl_i is not None and orb.sl_i != -1:
            total -= _diff_pct(orb.sl_px, orb.entry_px) * (1.0 - taken)
            if taken == 0.0:
                losses += 1
        if success:
            wins += 1
    n = wins + losses
    return {
        "total_days": len(result.orbs),
        "wins": wins,
        "losses": losses,
        "winrate_pct": round(100.0 * wins / n, 2) if n else None,
        "avg_profit_pct": round(float(total) / n, 2) if n else None,
        "total_profit_pct": round(float(total), 2),
    }
