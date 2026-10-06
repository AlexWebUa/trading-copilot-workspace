"""
Detector combinations — "trigger, then zone, then retest" chains (research 2026-10-03).

Why a standalone simulator and not a `SetupRule`: the rule DSL is a conjunction
of detector STATES on one bar. It has no "event A, then event B within N bars",
it cannot bind the entry zone to the FVG that satisfied the condition, and its
`*_near` limit fill leaves the fill bar unchecked against the stop. On 3m/5m it
would also re-run every detector on a growing slice per bar. Here every event
stream is computed once over the frame and carries the bar at whose CLOSE it
became known; nothing is read before that bar.

Layout:

  pools     price levels resting liquidity sits behind, each with the bar range
            in which it is live: 5-candle fractals, the previous day's extreme,
            the Asia / London session extremes.
  sweeps    the first bar that takes a live pool by WICK and closes back — the
            only sweep definition the project has (`detectors/liquidity.py`),
            with its 0.15 ATR threshold, on a per-bar ATR.
  zones     FVGs, inverted FVGs, order blocks, the band two opposite gaps share.
  flow      `detect_order_flow` in one causal pass: direction, BOS and cBOS.
  chains    fourteen ways to turn those into a setup — entry level, stop and
            the bar it is known at. A1 is the trader's example of 2026-10-03;
            the catalogue and every definition are in docs/SETUP_COMBOS.md.
  execute   one resting limit, one position, honest fills.

Everything is written for the LONG side. A short arm runs the same code on the
mirrored frame (prices negated, high and low swapped), so the two sides cannot
drift apart; prices are mirrored back in the trade table.

Execution rules, each one a place earlier setups of this project went wrong:

  - the limit rests from the bar AFTER the setup is known and fills at its
    level, or at the open when the bar opens through it;
  - the fill bar is checked against the stop, and the stop wins a bar that
    reaches both; a take-profit on the fill bar counts only if that bar CLOSED
    beyond it — the high may predate the fill, the close cannot;
  - a setup whose stop would sit on the wrong side of the entry is not a trade;
  - zone state is tracked here, bar by bar. Detector fields such as `fill_state`
    or `is_mitigated` describe the END of the slice and are never read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from copilot.detectors.order_flow import detect_order_flow
from copilot.detectors.smc_lib import true_range_atr

_KYIV = ZoneInfo("Europe/Kyiv")
_NY = ZoneInfo("America/New_York")
# The trader's sessions (2026-10-06), Kyiv wall clock, as minutes of the local
# day. London and New York overlap 15:00-18:00. A session extreme stays a pool
# for "5 дней (рабочая неделя)" — read as five business days, i.e. seven
# calendar days from the session's close.
_SESSIONS = ((2 * 60, 10 * 60), (10 * 60, 18 * 60), (15 * 60, 23 * 60))
_SESSION_POOL_LIFE = pd.Timedelta(days=7)

POOLS = ("fractal", "prev_day", "session")
# Detector defaults, kept as they are (RESEARCH_PROTOCOL §7): how old a gap may
# be and still count as live (`detect_fvg` max_age_bars), and how long a gap has
# to be closed through (`detect_ifvg` lookback).
_FVG_MAX_AGE = 200
_IFVG_LOOKBACK = 300


@dataclass(frozen=True)
class ComboParams:
    chain: str = "A1"
    side: str = "long"              # "long" | "short"
    pool: str = "fractal"           # what the sweep takes: see POOLS
    fractal_k: int = 2              # candles each side: 2 = the 5-candle fractal
    sweep_tol_atr: float = 0.15     # wick must exceed the pool by this (detect_liquidity default)
    fvg_min_atr: float = 0.1        # minimum gap width (detect_fvg default), ATR at C2
    entry: str = "near"             # "near": first touch of the zone; "ce": its midpoint
    tp_r: float = 2.0
    target: str = "rr"              # "rr": tp_r times the risk; "htf_fractal": see `simulate`
    min_rr: float = 1.8             # skip a setup whose structural target pays less (trader's floor)
    fill_hours_ny: tuple[int, int] | None = None   # fills only inside [start, end) New York
    max_wait_bars: int = 20         # life of the resting limit
    link_bars: int = 20             # sweep -> confirming break / inversion, at most
    ob_swing_k: int = 5             # swing width of the order-block scan (detector default)
    min_stop_atr: float = 0.5       # stop floor, ATR at the bar the setup is known
    cost_bps: float = 6.0           # fee + slippage per side


@dataclass(frozen=True)
class _Bars:
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    atr: np.ndarray

    def mirror(self) -> "_Bars":
        return _Bars(-self.o, -self.l, -self.h, -self.c, self.atr)


@dataclass(frozen=True)
class _Pools:
    """Lows with resting sell-side liquidity. Pool k is live on bars
    [live_from[k], live_to[k]) — never before it is known."""
    level: np.ndarray
    live_from: np.ndarray
    live_to: np.ndarray


@dataclass
class _Setup:
    known_i: int        # bar at whose close the setup exists
    trigger_i: int      # the sweep bar
    entry: float        # near edge of the zone
    stop: float
    far: float          # far edge of the zone
    floor_hit: bool = False
    tp: float | None = None         # a structural target; None = tp_r times the risk


@dataclass
class ComboResult:
    params: ComboParams
    trades: pd.DataFrame
    funnel: dict = field(default_factory=dict)


# ── Bars ────────────────────────────────────────────────────────────────────

def _bars(df: pd.DataFrame) -> _Bars:
    f64 = np.float64
    return _Bars(
        df["open"].to_numpy(f64), df["high"].to_numpy(f64),
        df["low"].to_numpy(f64), df["close"].to_numpy(f64),
        np.asarray(true_range_atr(df), dtype=f64),
    )


# ── Pools ───────────────────────────────────────────────────────────────────

def _fractal_pools(b: _Bars, k: int) -> _Pools:
    """Strict Williams fractal lows: lower than each of the k bars on both sides.

    The pivot at j is known when bar j+k closes, so the first bar that can take
    it is j+k+1.
    """
    n = len(b.l)
    if n < 2 * k + 1:
        return _Pools(np.empty(0), np.empty(0, np.int64), np.empty(0, np.int64))
    mid = b.l[k:n - k]
    ok = np.ones(n - 2 * k, dtype=bool)
    for d in range(1, k + 1):
        ok &= (mid < b.l[k - d:n - k - d]) & (mid < b.l[k + d:n - k + d])
    piv = np.flatnonzero(ok) + k
    return _Pools(b.l[piv], piv + k + 1, np.full(len(piv), n, dtype=np.int64))


def _day_slices(codes: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) bar ranges of consecutive runs of equal `codes`."""
    if len(codes) == 0:
        return []
    cuts = np.flatnonzero(np.diff(codes)) + 1
    starts = np.concatenate(([0], cuts))
    ends = np.concatenate((cuts, [len(codes)]))
    return list(zip(starts.tolist(), ends.tolist()))


def _prev_day_pools(b: _Bars, index: pd.DatetimeIndex) -> _Pools:
    """The previous UTC day's low, live for the whole of the following day.

    The frame's first day is skipped as a source: it may be cut short, and a
    partial day's low is not the previous day's low.
    """
    days = _day_slices(index.tz_convert("UTC").normalize().asi8)
    level, lo, hi = [], [], []
    for (ps, pe), (s, e) in zip(days[1:], days[2:]):
        level.append(b.l[ps:pe].min())
        lo.append(s)
        hi.append(e)
    return _Pools(np.array(level), np.array(lo, np.int64), np.array(hi, np.int64))


def _session_pools(b: _Bars, index: pd.DatetimeIndex) -> _Pools:
    """Asia, London and New York lows, each a pool from the bar after its session
    closes until `_SESSION_POOL_LIFE` later.

    Wall-clock Kyiv time through the tz database, not a fixed UTC offset: the
    offset moves twice a year. Weekend days build no pools (a pool built on
    Friday still lives through the weekend). Masks rather than `searchsorted`
    for the session, because on the autumn changeover day the local clock runs
    03:00-04:00 twice and is not monotonic; the pool's end is found by
    timestamp, not by counting bars.
    """
    n = len(index)
    local = index.tz_convert(_KYIV)
    minute = (local.hour * 60 + local.minute).to_numpy()
    weekday = local.dayofweek.to_numpy()
    days = _day_slices(local.tz_localize(None).normalize().asi8)
    level, lo, hi = [], [], []
    for s, e in days[1:]:                     # first local day may be partial
        if weekday[s] >= 5:
            continue
        m = minute[s:e]
        for start, end in _SESSIONS:
            sess = np.flatnonzero((m >= start) & (m < end))
            if len(sess) == 0:
                continue
            first_live = s + int(sess[-1]) + 1
            if first_live >= n:
                continue
            level.append(b.l[s + sess[0]:first_live].min())
            lo.append(first_live)
            hi.append(int(index.searchsorted(index[first_live] + _SESSION_POOL_LIFE)))
    return _Pools(np.array(level), np.array(lo, np.int64), np.array(hi, np.int64))


def _pools(b: _Bars, index: pd.DatetimeIndex, p: ComboParams) -> _Pools:
    if p.pool == "fractal":
        return _fractal_pools(b, p.fractal_k)
    if p.pool == "prev_day":
        return _prev_day_pools(b, index)
    if p.pool == "session":
        return _session_pools(b, index)
    raise ValueError(f"pool {p.pool!r}")


# ── Sweeps ──────────────────────────────────────────────────────────────────

def _sweep_bars(b: _Bars, pools: _Pools, tol_atr: float) -> np.ndarray:
    """Bars that take a live pool by wick and close back above it, ascending.

    `detectors/liquidity.py`, bar for bar: scanning forward from the pool, the
    first bar whose low is more than the tolerance below the level decides it.
    Close back above the level: a sweep, and the pool is spent. Close more than
    the tolerance below: a break, the pool is gone and there is no sweep. A
    close inside the tolerance band is neither, and the scan goes on. The
    tolerance is the bar's own ATR, not the ATR of whenever one happens to look.

    A bar that takes several pools is one sweep.
    """
    reach = b.l + tol_atr * b.atr          # low[i] < level - tol[i]  <=>  reach[i] < level
    found = []
    for level, a, end in zip(pools.level, pools.live_from, pools.live_to):
        i = int(a)
        end = int(end)
        step = 32
        while i < end:
            stop = min(end, i + step)
            hit = np.flatnonzero(reach[i:stop] < level)
            if len(hit) == 0:
                i = stop
                step = min(step * 4, 1 << 16)
                continue
            j = i + int(hit[0])
            if b.c[j] > level:
                found.append(j)
                break
            if b.c[j] < level - tol_atr * b.atr[j]:
                break
            i = j + 1
    return np.unique(np.array(found, dtype=np.int64))


# ── Zones ───────────────────────────────────────────────────────────────────

def _fvgs(b: _Bars, min_atr: float, bullish: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Three-candle gaps as (c2, top, bottom), ascending by C2 — the bar at whose
    close the gap is known. Width is measured against the ATR of C2 itself;
    `detect_fvg` measures every historical gap against the ATR of the slice's
    LAST bar, so there the same gap passes or fails depending on when one looks.
    """
    if len(b.c) < 3:
        e = np.empty(0)
        return np.empty(0, np.int64), e, e
    if bullish:
        top, bot = b.l[2:], b.h[:-2]
    else:
        top, bot = b.l[:-2], b.h[2:]
    gap = top - bot
    ok = (gap > 0) & (gap >= min_atr * b.atr[2:])
    return np.flatnonzero(ok) + 2, top[ok], bot[ok]


def _first_close_above(c: np.ndarray, level: float, a: int, end: int) -> int:
    """First bar in [a, end) closing above `level`, or -1."""
    step = 32
    while a < end:
        stop = min(end, a + step)
        hit = np.flatnonzero(c[a:stop] > level)
        if len(hit):
            return a + int(hit[0])
        a, step = stop, step * 4
    return -1


def _ifvgs(b: _Bars, min_atr: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Bearish gaps a later BODY closed through upward: (pierce bar, c2, top,
    bottom), ascending by pierce bar. The inversion is known at the pierce bar's
    close — `detect_ifvg` reports the gap's own timestamp, which is earlier.
    A gap is given `_IFVG_LOOKBACK` bars to be pierced, the detector's window.
    """
    c2, top, bot = _fvgs(b, min_atr, bullish=False)
    n = len(b.c)
    rows = []
    for j, t, lo in zip(c2.tolist(), top.tolist(), bot.tolist()):
        q = _first_close_above(b.c, t, j + 1, min(n, j + 1 + _IFVG_LOOKBACK))
        if q >= 0:
            rows.append((q, j, t, lo))
    rows.sort()
    if not rows:
        e = np.empty(0)
        return np.empty(0, np.int64), np.empty(0, np.int64), e, e
    q, j, t, lo = zip(*rows)
    return np.array(q, np.int64), np.array(j, np.int64), np.array(t), np.array(lo)


def _order_blocks(b: _Bars, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Bullish order blocks as (break bar, OB bar), ascending by break bar.

    `detectors/order_block.scan_order_blocks`, made causal. That scan tests the
    most recent swing high with idx < i, taken from swings found on the WHOLE
    frame — a swing still k bars short of confirmation shadows the older one a
    live reader would be testing, and the break of the older one is never
    reported. Here the swing must be confirmed (idx + k < i) before it is used.
    Same definition otherwise: a raw swing high (the maximum of its 2k+1 window),
    broken by a close; the OB is the lowest-low candle between the two.
    """
    n = len(b.c)
    if n < 2 * k + 1:
        return np.empty(0, np.int64), np.empty(0, np.int64)
    roll = np.lib.stride_tricks.sliding_window_view(b.h, 2 * k + 1).max(axis=1)
    swings = (np.flatnonzero(b.h[k:n - k] == roll) + k).tolist()
    breaks, obs = [], []
    ptr = -1
    crossed = -1
    for i in range(n):
        while ptr + 1 < len(swings) and swings[ptr + 1] + k < i:
            ptr += 1
        if ptr < 0:
            continue
        s = swings[ptr]
        if s == crossed or b.c[i] <= b.h[s]:
            continue
        crossed = s
        if i - s < 2:
            continue
        seg = b.l[s + 1:i]
        breaks.append(i)
        obs.append(s + 1 + int(np.flatnonzero(seg == seg.min())[-1]))
    return np.array(breaks, np.int64), np.array(obs, np.int64)


# ── Order flow ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FlowStreams:
    """`detect_order_flow` over a whole frame, in bar positions.

    The walk only appends: its state after bar k depends on bars <= k, so one
    pass yields every event with the bar that caused it. `bias[i]` is the
    direction of the last event whose bar is <= i, i.e. known at bar i's close.
    """
    bias: np.ndarray            # +1 bullish / -1 bearish / 0 none yet
    break_i: np.ndarray         # the bar whose body closed through the key
    broken_i: np.ndarray        # the bar where the broken key printed
    direction: np.ndarray       # +1 / -1
    is_bos: np.ndarray          # True = structure break (BOS), False = continuation (cBOS)

    def cut(self, n: int) -> "FlowStreams":
        keep = self.break_i < n
        return FlowStreams(self.bias[:n], self.break_i[keep], self.broken_i[keep],
                           self.direction[keep], self.is_bos[keep])


def flow_streams(df: pd.DataFrame) -> FlowStreams:
    n = len(df)
    res = detect_order_flow(df, swing_lookback=1, max_events=10**9, lookback=0)
    events = list(reversed(res.get("events", [])))          # detector returns newest first
    if not events:
        e = np.empty(0, np.int64)
        return FlowStreams(np.zeros(n, np.int8), e, e, np.empty(0, np.int8), np.empty(0, bool))

    def pos(key: str) -> np.ndarray:
        ts = pd.DatetimeIndex(pd.to_datetime([ev[key] for ev in events], utc=True))
        out = df.index.get_indexer(ts.as_unit(df.index.unit))
        if (out < 0).any():
            raise RuntimeError(f"order-flow {key} not on the frame's index")
        return out.astype(np.int64)

    break_i, broken_i = pos("break_ts"), pos("broken_ts")
    direction = np.array([1 if ev["direction"] == "bullish" else -1 for ev in events], np.int8)
    is_bos = np.array([ev["type"] == "BOS" for ev in events], bool)
    last = np.searchsorted(break_i, np.arange(n), side="right") - 1
    bias = np.where(last >= 0, direction[np.maximum(last, 0)], 0).astype(np.int8)
    return FlowStreams(bias, break_i, broken_i, direction, is_bos)


def release_bias(event_open: pd.DatetimeIndex, direction: np.ndarray, htf_minutes: int,
                 index: pd.DatetimeIndex, bar_minutes: int) -> np.ndarray:
    """Higher-timeframe direction as of each bar's close on `index` (+1 / -1 / 0).

    `event_open` are the OPEN times of the higher-timeframe candles whose body
    made each break, ascending. A break is known only when that candle has
    closed, `htf_minutes` later; releasing it at the open would hand every
    lower-timeframe bar inside the candle a close that had not happened yet.
    """
    if len(event_open) == 0:
        return np.zeros(len(index), np.int8)
    known = (event_open + pd.Timedelta(minutes=htf_minutes)).as_unit("ns").asi8
    closes = (index + pd.Timedelta(minutes=bar_minutes)).as_unit("ns").asi8
    pos = np.searchsorted(known, closes, side="right") - 1
    return np.where(pos >= 0, direction[np.maximum(pos, 0)], 0).astype(np.int8)


@dataclass(frozen=True)
class _Targets:
    """Higher-timeframe fractal highs, in the arm's price space, each with the
    bars of the trading frame on which it is a valid target: from the close that
    confirms it until a higher-timeframe body has closed above it."""
    level: np.ndarray
    avail_i: np.ndarray         # first bar whose close sees the fractal confirmed
    dead_i: np.ndarray          # first bar whose close sees it broken

    def nearest_above(self, i: int, price: float) -> float | None:
        ok = (self.avail_i <= i) & (self.dead_i > i) & (self.level > price)
        return float(self.level[ok].min()) if ok.any() else None


def _fractal_targets(htf: _Bars, htf_index: pd.DatetimeIndex, htf_minutes: int,
                     index: pd.DatetimeIndex, bar_minutes: int) -> _Targets:
    """3-candle fractal highs of the higher timeframe — the project's target
    convention (`simulate._FRACTAL_TARGET_POOL` takes `bars="3"` and drops only
    fractals a close has broken; a wick through one leaves it standing).

    A pivot at HTF bar j is confirmed when bar j+1 closes, and broken when a
    later HTF bar closes above it. Both moments are mapped to the first bar of
    the trading frame whose own close is not earlier — a lower-timeframe bar
    inside a still-open HTF candle knows neither.
    """
    n_htf = len(htf.h)
    closes = (index + pd.Timedelta(minutes=bar_minutes)).as_unit("ns").asi8
    htf_close = (htf_index + pd.Timedelta(minutes=htf_minutes)).as_unit("ns").asi8
    if n_htf < 3:
        e = np.empty(0, np.int64)
        return _Targets(np.empty(0), e, e)
    piv = np.flatnonzero((htf.h[1:-1] > htf.h[:-2]) & (htf.h[1:-1] > htf.h[2:])) + 1
    level = htf.h[piv]
    avail = np.searchsorted(closes, htf_close[piv + 1], side="left")
    dead = np.full(len(piv), len(index), dtype=np.int64)
    for k, (j, lv) in enumerate(zip(piv.tolist(), level.tolist())):
        m = _first_close_above(htf.c, lv, j + 2, n_htf)
        if m >= 0:
            dead[k] = np.searchsorted(closes, htf_close[m], side="left")
    return _Targets(level, avail.astype(np.int64), dead)


# ── Chains ──────────────────────────────────────────────────────────────────

@dataclass
class _Ctx:
    b: _Bars
    p: ComboParams
    index: pd.DatetimeIndex
    flow: FlowStreams | None
    sign: int                                   # +1 long arm, -1 short arm
    gate: np.ndarray | None = None              # bars on which a setup may arise
    targets: "_Targets | None" = None           # higher-timeframe fractals to aim at
    funnel: dict = field(default_factory=dict)
    _sweeps: np.ndarray | None = None

    def count(self, key: str, by: int = 1) -> None:
        self.funnel[key] = self.funnel.get(key, 0) + by

    def sweeps(self) -> np.ndarray:
        if self._sweeps is None:
            pools = _pools(self.b, self.index, self.p)
            self._sweeps = _sweep_bars(self.b, pools, self.p.sweep_tol_atr)
            self.funnel["pools"] = int(len(pools.level))
            self.funnel["sweeps"] = int(len(self._sweeps))
        return self._sweeps

    def _need_flow(self) -> FlowStreams:
        if self.flow is None:
            raise ValueError(f"chain {self.p.chain} needs order-flow streams")
        return self.flow

    def with_flow(self) -> np.ndarray:
        """True where the order flow, as of that bar's close, points the arm's way."""
        return self._need_flow().bias == self.sign

    def breaks(self, bos: bool) -> tuple[np.ndarray, np.ndarray]:
        """(break bar, broken-key bar) of the arm-direction events of one type."""
        f = self._need_flow()
        sel = (f.direction == self.sign) & (f.is_bos == bos)
        return f.break_i[sel], f.broken_i[sel]

    def wick_intact(self, t: int, upto: int) -> bool:
        """No bar after the sweep, up to and including `upto`, traded back to its wick."""
        return upto <= t or bool(self.b.l[t + 1:upto + 1].min() > self.b.l[t])


def _last_gap_in_leg(ctx: _Ctx, gaps: tuple, first_c2: int, last_c2: int, known: int):
    """The last bullish gap confirmed in [first_c2, last_c2], or None if there is
    none or price already came back to it by bar `known` — a zone retested before
    the setup exists is spent."""
    c2, top, bot = gaps
    lo = int(np.searchsorted(c2, first_c2, side="left"))
    hi = int(np.searchsorted(c2, last_c2, side="right"))
    if hi <= lo:
        ctx.count("no_zone")
        return None
    g = hi - 1
    j = int(c2[g])
    if known > j and ctx.b.l[j + 1:known + 1].min() <= top[g]:
        ctx.count("zone_spent")
        return None
    return j, float(top[g]), float(bot[g])


def _chain_a1(ctx: _Ctx) -> list[_Setup]:
    """Sweep on bar t, then a bullish FVG whose impulse candle C1 is t+1 or t+2.

    C0, C1, C2 are (t, t+1, t+2) or (t+1, t+2, t+3); the first that qualifies is
    taken. The gap is known when C2 closes. Entry is its near edge, low[C2]; the
    stop is the sweep wick, low[t]. If price trades back to the wick before C2
    closes, the wick is no longer the extreme of the move and the setup is void.
    """
    b, p = ctx.b, ctx.p
    n = len(b.c)
    out = []
    for t in ctx.sweeps().tolist():
        found = False
        for c0 in (t, t + 1):
            c2 = c0 + 2
            if c2 >= n:
                break
            gap = b.l[c2] - b.h[c0]
            if gap <= 0 or gap < p.fvg_min_atr * b.atr[c2]:
                continue
            found = True
            if ctx.wick_intact(t, c2):
                out.append(_Setup(c2, t, float(b.l[c2]), float(b.l[t]), float(b.h[c0])))
            else:
                ctx.count("wick_broken")
            break
        if not found:
            ctx.count("no_zone")
    return out


def _chain_a2(ctx: _Ctx) -> list[_Setup]:
    """Sweep on bar t, and the sweep candle becomes an order block: within
    `link_bars` a close breaks the swing high above it, with the sweep candle the
    lowest low of that leg. Known at the break. Entry is the top of the sweep
    candle, the stop its wick."""
    b, p = ctx.b, ctx.p
    brk, ob = _order_blocks(b, p.ob_swing_k)
    break_of = dict(zip(ob.tolist(), brk.tolist()))
    out = []
    for t in ctx.sweeps().tolist():
        i = break_of.get(t)
        if i is None or i - t > p.link_bars:
            ctx.count("no_zone")
        elif not ctx.wick_intact(t, i):
            ctx.count("wick_broken")
        else:
            out.append(_Setup(i, t, float(b.h[t]), float(b.l[t]), float(b.l[t])))
    return out


def _chain_a3(ctx: _Ctx) -> list[_Setup]:
    """Sweep on bar t, then a bearish gap that existed at the sweep is closed
    through by a body within `link_bars`: the first such inversion. Known at the
    pierce bar. Entry is the gap's upper edge, the stop the sweep wick."""
    b, p = ctx.b, ctx.p
    q, c2, top, bot = _ifvgs(b, p.fvg_min_atr)
    out = []
    for t in ctx.sweeps().tolist():
        lo = int(np.searchsorted(q, t, side="right"))
        hi = int(np.searchsorted(q, t + p.link_bars, side="right"))
        pick = next((g for g in range(lo, hi) if c2[g] <= t), None)
        if pick is None:
            ctx.count("no_zone")
        elif not ctx.wick_intact(t, int(q[pick])):
            ctx.count("wick_broken")
        else:
            out.append(_Setup(int(q[pick]), t, float(top[pick]), float(b.l[t]), float(bot[pick])))
    return out


def _bpr_band(ctx: _Ctx, bear: tuple, c2: int, top: float, bot: float):
    """(top, bottom) of the band a bullish gap (confirmed at c2) shares with the
    most recent earlier bearish gap that is still alive: formed within
    `_FVG_MAX_AGE` bars and not yet traded through to its far edge. None if there
    is no such band."""
    bc2, btop, bbot = bear
    hi = int(np.searchsorted(bc2, c2 - 2, side="left"))         # formed before our C0
    lo = int(np.searchsorted(bc2, c2 - _FVG_MAX_AGE, side="left"))
    for g in range(hi - 1, lo - 1, -1):
        j = int(bc2[g])
        if min(top, btop[g]) <= max(bot, bbot[g]):
            continue
        if ctx.b.h[j + 1:c2 + 1].max() >= btop[g]:
            continue
        return float(min(top, btop[g])), float(max(bot, bbot[g]))
    return None


def _chain_a4(ctx: _Ctx) -> list[_Setup]:
    """A1 whose gap overlaps a live bearish gap: a BPR. Entry is the top of the
    shared band, the stop the sweep wick."""
    b, p = ctx.b, ctx.p
    n = len(b.c)
    bear = _fvgs(b, p.fvg_min_atr, bullish=False)
    out = []
    for t in ctx.sweeps().tolist():
        found = False
        for c0 in (t, t + 1):
            c2 = c0 + 2
            if c2 >= n:
                break
            gap = b.l[c2] - b.h[c0]
            if gap <= 0 or gap < p.fvg_min_atr * b.atr[c2]:
                continue
            band = _bpr_band(ctx, bear, c2, float(b.l[c2]), float(b.h[c0]))
            if band is None:
                continue
            found = True
            if ctx.wick_intact(t, c2):
                out.append(_Setup(c2, t, band[0], float(b.l[t]), band[1]))
            else:
                ctx.count("wick_broken")
            break
        if not found:
            ctx.count("no_zone")
    return out


def _chain_a5(ctx: _Ctx) -> list[_Setup]:
    """Sweep on bar t, then a structure break (BOS) the arm's way within
    `link_bars`, with a gap left by the leg from the sweep to the break — the
    last one whose impulse candle lies in (t, break]. Entry is its near edge,
    the stop the sweep wick."""
    b, p = ctx.b, ctx.p
    n = len(b.c)
    brk, _ = ctx.breaks(bos=True)
    gaps = _fvgs(b, p.fvg_min_atr, bullish=True)
    out = []
    for t in ctx.sweeps().tolist():
        g = int(np.searchsorted(brk, t, side="right"))
        if g >= len(brk) or brk[g] - t > p.link_bars:
            ctx.count("no_break")
            continue
        i = int(brk[g])
        last_c2 = min(i + 1, n - 1)
        hit = _last_gap_in_leg(ctx, gaps, t + 2, last_c2, max(i, last_c2))
        if hit is None:
            continue
        j, top, bot = hit
        known = max(i, j)
        if not ctx.wick_intact(t, known):
            ctx.count("wick_broken")
            continue
        out.append(_Setup(known, t, top, float(b.l[t]), bot))
    return out


def _leg_origin(b: _Bars, broken: int, i: int) -> int:
    """The lowest low between the broken key and the break: where the breaking
    leg started. This is the low that becomes the flow's key low once the break
    resolves, read here from bars alone rather than from the walker's later,
    back-filled state."""
    seg = b.l[broken:i + 1]
    return broken + int(np.flatnonzero(seg == seg.min())[-1])


def _chain_break_fvg(ctx: _Ctx, bos: bool) -> list[_Setup]:
    """A break the arm's way (BOS or cBOS), and the last gap left by the breaking
    leg. Entry is its near edge, the stop the low the leg started from."""
    b, p = ctx.b, ctx.p
    n = len(b.c)
    gaps = _fvgs(b, p.fvg_min_atr, bullish=True)
    out = []
    for i, broken in zip(*(a.tolist() for a in ctx.breaks(bos))):
        origin = _leg_origin(b, broken, i)
        last_c2 = min(i + 1, n - 1)
        hit = _last_gap_in_leg(ctx, gaps, origin + 2, last_c2, max(i, last_c2))
        if hit is None:
            continue
        j, top, bot = hit
        out.append(_Setup(max(i, j), i, top, float(b.l[origin]), bot))
    return out


def _chain_break_ob(ctx: _Ctx, bos: bool) -> list[_Setup]:
    """A break the arm's way (BOS or cBOS), and its order block: the lowest-low
    candle between the broken key and the break. Entry is the top of that
    candle, the stop its low."""
    b = ctx.b
    out = []
    for i, broken in zip(*(a.tolist() for a in ctx.breaks(bos))):
        if i - broken < 2:
            ctx.count("no_zone")
            continue
        seg = b.l[broken + 1:i]
        ob = broken + 1 + int(np.flatnonzero(seg == seg.min())[-1])
        if b.l[i] <= b.l[ob]:
            ctx.count("zone_spent")
            continue
        out.append(_Setup(i, i, float(b.h[ob]), float(b.l[ob]), float(b.l[ob])))
    return out


def _chain_fvg(ctx: _Ctx, flow: bool) -> list[_Setup]:
    """Every bullish gap (C0), or only those confirmed while the order flow
    points the arm's way (C1). Entry is the near edge, the stop the low of the
    two candles that made the gap."""
    b = ctx.b
    c2, top, bot = _fvgs(b, ctx.p.fvg_min_atr, bullish=True)
    if flow:
        keep = ctx.with_flow()[c2]
        ctx.count("against_flow", int((~keep).sum()))
        c2, top, bot = c2[keep], top[keep], bot[keep]
    stop = np.minimum(b.l[c2 - 2], b.l[c2 - 1])
    return [_Setup(int(j), int(j), float(e), float(s), float(f))
            for j, e, s, f in zip(c2, top, stop, bot)]


def _chain_c2(ctx: _Ctx) -> list[_Setup]:
    """An order block (swing-break definition) confirmed while the order flow
    points the arm's way. Entry is the top of the OB candle, the stop its low."""
    b = ctx.b
    brk, ob = _order_blocks(b, ctx.p.ob_swing_k)
    ok = ctx.with_flow()
    out = []
    for i, o in zip(brk.tolist(), ob.tolist()):
        if not ok[i]:
            ctx.count("against_flow")
        elif b.l[i] <= b.l[o]:
            ctx.count("zone_spent")
        else:
            out.append(_Setup(i, i, float(b.h[o]), float(b.l[o]), float(b.l[o])))
    return out


def _chain_c3(ctx: _Ctx) -> list[_Setup]:
    """A bearish gap closed through by a body while the order flow points the
    arm's way. Entry is the gap's upper edge, the stop its lower edge."""
    q, _, top, bot = _ifvgs(ctx.b, ctx.p.fvg_min_atr)
    ok = ctx.with_flow()
    out = []
    for i, e, s in zip(q.tolist(), top.tolist(), bot.tolist()):
        if ok[i]:
            out.append(_Setup(i, i, e, s, s))
        else:
            ctx.count("against_flow")
    return out


def _chain_c4(ctx: _Ctx) -> list[_Setup]:
    """A bullish gap that overlaps a live bearish one, confirmed while the order
    flow points the arm's way. Entry is the top of the shared band, the stop the
    bottom of the bullish gap."""
    b, p = ctx.b, ctx.p
    bear = _fvgs(b, p.fvg_min_atr, bullish=False)
    ok = ctx.with_flow()
    out = []
    for j, top, bot in zip(*(a.tolist() for a in _fvgs(b, p.fvg_min_atr, bullish=True))):
        if not ok[j]:
            ctx.count("against_flow")
            continue
        band = _bpr_band(ctx, bear, j, top, bot)
        if band is None:
            ctx.count("no_zone")
        else:
            out.append(_Setup(j, j, band[0], bot, band[1]))
    return out


_CHAIN_FN = {
    "A1": _chain_a1,
    "A2": _chain_a2,
    "A3": _chain_a3,
    "A4": _chain_a4,
    "A5": _chain_a5,
    "B1": lambda ctx: _chain_break_fvg(ctx, bos=True),
    "B2": lambda ctx: _chain_break_ob(ctx, bos=True),
    "B3": lambda ctx: _chain_break_fvg(ctx, bos=False),
    "B4": lambda ctx: _chain_break_ob(ctx, bos=False),
    "C0": lambda ctx: _chain_fvg(ctx, flow=False),
    "C1": lambda ctx: _chain_fvg(ctx, flow=True),
    "C2": _chain_c2,
    "C3": _chain_c3,
    "C4": _chain_c4,
}
CHAINS = tuple(_CHAIN_FN)
FLOW_CHAINS = ("A5", "B1", "B2", "B3", "B4", "C1", "C2", "C3", "C4")


def _finish(ctx: _Ctx, raw: list[_Setup]) -> list[_Setup]:
    """Drop setups whose stop is not below the entry, apply the stop floor, and
    keep one setup per bar: the zone price reaches first, then the wider stop.

    Two sweeps can lead into the same gap (bars t and t+1 both took a pool):
    that is one setup, with the stop behind the lower wick — the extreme of the
    whole sweep.
    """
    b, p = ctx.b, ctx.p
    by_known: dict[int, _Setup] = {}
    for s in raw:
        if ctx.gate is not None and not ctx.gate[s.known_i]:
            ctx.count("gated")
            continue
        if p.entry == "ce":
            s.entry = (s.entry + s.far) / 2.0
        if s.stop >= s.entry:
            ctx.count("wrong_side")
            continue
        floor = s.entry - p.min_stop_atr * b.atr[s.known_i]
        if floor < s.stop:
            s.stop = float(floor)
            s.floor_hit = True
        if ctx.targets is not None:
            tp = ctx.targets.nearest_above(s.known_i, s.entry)
            if tp is None:
                ctx.count("no_target")
                continue
            if (tp - s.entry) / (s.entry - s.stop) < p.min_rr:
                ctx.count("rr_too_low")
                continue
            s.tp = tp
        prev = by_known.get(s.known_i)
        if prev is None or (s.entry, -s.stop) > (prev.entry, -prev.stop):
            by_known[s.known_i] = s
    setups = [by_known[k] for k in sorted(by_known)]
    ctx.funnel["setups"] = len(setups)
    return setups


# ── Execution ───────────────────────────────────────────────────────────────

def _execute(b: _Bars, setups: list[_Setup], p: ComboParams,
             can_fill: np.ndarray | None = None) -> tuple[list[dict], dict]:
    """`can_fill`, if given, marks the bars a limit may fill on. A touch on any
    other bar spends the zone: the order is dropped, not carried into the window."""
    funnel = {"skipped_in_position": 0, "replaced": 0, "expired": 0, "ran_away": 0,
              "gapped_through_stop": 0, "outside_window": 0, "filled": 0, "unfinished": 0}
    trades: list[dict] = []
    n = len(b.c)
    o, h, lo, c = b.o, b.h, b.l, b.c
    pos: dict | None = None
    pend: _Setup | None = None
    place_i = 0
    tp = 0.0
    si = 0
    n_setups = len(setups)

    def close(trade: dict, i: int, px: float, kind: str) -> None:
        trade.update(exit_i=i, exit=px, exit_kind=kind)
        trades.append(trade)

    for i in range(n):
        if pos is not None:
            if lo[i] <= pos["stop"]:
                close(pos, i, min(o[i], pos["stop"]), "sl")
                pos = None
            elif h[i] >= pos["tp"]:
                close(pos, i, pos["tp"], "tp")
                pos = None
        elif pend is not None and i >= place_i:
            if i - place_i >= p.max_wait_bars:
                funnel["expired"] += 1
                pend = None
            elif lo[i] <= pend.entry:
                if can_fill is not None and not can_fill[i]:
                    funnel["outside_window"] += 1
                elif o[i] <= pend.stop:
                    # Opened beyond the stop: the limit would fill straight
                    # into a stopped-out position at an undefined risk.
                    funnel["gapped_through_stop"] += 1
                else:
                    funnel["filled"] += 1
                    trade = {"known_i": pend.known_i, "trigger_i": pend.trigger_i,
                             "entry_i": i, "entry": min(o[i], pend.entry),
                             "stop": pend.stop, "tp": tp, "floor_hit": pend.floor_hit}
                    if lo[i] <= pend.stop:
                        close(trade, i, pend.stop, "sl")
                    elif c[i] >= tp:
                        close(trade, i, tp, "tp")
                    else:
                        pos = trade
                pend = None
            elif h[i] >= tp:
                # Reached the target without coming back for us.
                funnel["ran_away"] += 1
                pend = None

        while si < n_setups and setups[si].known_i == i:
            s = setups[si]
            si += 1
            if pos is not None:
                funnel["skipped_in_position"] += 1
                continue
            if pend is not None:
                funnel["replaced"] += 1
            pend = s
            place_i = i + 1
            tp = s.tp if s.tp is not None else s.entry + p.tp_r * (s.entry - s.stop)

    if pos is not None:
        funnel["unfinished"] += 1
        pos.update(exit_i=-1, exit=np.nan, exit_kind="open")
        trades.append(pos)
    return trades, funnel


# ── Public ──────────────────────────────────────────────────────────────────

TRADE_COLUMNS = [
    "known_ts", "trigger_ts", "entry_ts", "exit_ts", "side", "entry", "stop", "tp",
    "exit", "exit_kind", "closed", "floor_hit", "risk_pct", "risk_atr", "gross_r",
    "cost_r", "r", "known_i", "trigger_i", "entry_i", "exit_i",
]


def sweep_bars(df: pd.DataFrame, params: ComboParams = ComboParams()) -> np.ndarray:
    """Indices of the bars that sweep a pool on `params.side`'s trigger side."""
    b = _bars(df)
    if params.side == "short":
        b = b.mirror()
    return _sweep_bars(b, _pools(b, df.index, params), params.sweep_tol_atr)


def simulate(df: pd.DataFrame, params: ComboParams = ComboParams(),
             flow: FlowStreams | None = None, gate: np.ndarray | None = None,
             htf: tuple[pd.DataFrame, int, int] | None = None) -> ComboResult:
    """Run one arm over `df` (canonical OHLCV, UTC index).

    `gate`, if given, is one boolean per bar: a setup that becomes known on a
    bar where it is False is dropped. It carries context the frame itself does
    not hold — a higher-timeframe bias — and, like every stream here, may only
    reflect what was known by that bar's close.

    `htf` is `(frame, its bar minutes, df's bar minutes)` of a higher timeframe.
    With `params.target == "htf_fractal"` the take-profit is the nearest of its
    3-candle fractals beyond the entry that is confirmed and unbroken when the
    setup arises; a setup with no such fractal, or one paying less than
    `params.min_rr`, is not traded. The frame must not run past `df`.

    `flow` is `flow_streams(df)` — required by the chains in `FLOW_CHAINS`, and
    passed in rather than computed here because it is the one slow stream and is
    the same for every arm on a timeframe.
    """
    if params.side not in ("long", "short"):
        raise ValueError(f"side {params.side!r}")
    if params.chain not in _CHAIN_FN:
        raise ValueError(f"chain {params.chain!r}")
    real = _bars(df)
    short = params.side == "short"
    b = real.mirror() if short else real
    sign = -1.0 if short else 1.0

    if params.target not in ("rr", "htf_fractal"):
        raise ValueError(f"target {params.target!r}")
    targets = None
    if params.target == "htf_fractal":
        if htf is None:
            raise ValueError("target 'htf_fractal' needs the higher-timeframe frame")
        htf_df, htf_minutes, bar_minutes = htf
        hb = _bars(htf_df)
        targets = _fractal_targets(hb.mirror() if short else hb, htf_df.index, htf_minutes,
                                   df.index, bar_minutes)
    ctx = _Ctx(b, params, df.index, flow, -1 if short else 1, gate, targets)
    if params.entry not in ("near", "ce"):
        raise ValueError(f"entry {params.entry!r}")
    setups = _finish(ctx, _CHAIN_FN[params.chain](ctx))
    can_fill = None
    if params.fill_hours_ny is not None:
        hour = df.index.tz_convert(_NY).hour.to_numpy()
        can_fill = (hour >= params.fill_hours_ny[0]) & (hour < params.fill_hours_ny[1])
    raw, exec_funnel = _execute(b, setups, params, can_fill)
    funnel = {**ctx.funnel, **exec_funnel}

    index = df.index
    rows = []
    for t in raw:
        entry, stop, exit_px = sign * t["entry"], sign * t["stop"], sign * t["exit"]
        closed = t["exit_kind"] != "open"
        risk = abs(entry - stop)
        gross_r = sign * (exit_px - entry) / risk if closed else np.nan
        cost_r = (entry + exit_px) * params.cost_bps / 10_000 / risk if closed else np.nan
        rows.append({
            "known_ts": index[t["known_i"]],
            "trigger_ts": index[t["trigger_i"]],
            "entry_ts": index[t["entry_i"]],
            "exit_ts": index[t["exit_i"]] if closed else pd.NaT,
            "side": params.side,
            "entry": entry,
            "stop": stop,
            "tp": sign * t["tp"],
            "exit": exit_px,
            "exit_kind": t["exit_kind"],
            "closed": closed,
            "floor_hit": t["floor_hit"],
            "risk_pct": risk / entry * 100.0,
            "risk_atr": risk / real.atr[t["known_i"]],
            "gross_r": gross_r,
            "cost_r": cost_r,
            "r": gross_r - cost_r,
            "known_i": t["known_i"],
            "trigger_i": t["trigger_i"],
            "entry_i": t["entry_i"],
            "exit_i": t["exit_i"],
        })
    return ComboResult(params, pd.DataFrame(rows, columns=TRADE_COLUMNS), funnel)
