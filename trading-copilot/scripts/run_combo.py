#!/usr/bin/env python
r"""Detector combinations — staged research on BTCUSDT futures (2026-10-03) and,
with `--symbol XAUUSD`, on spot gold (2026-10-06).

    .venv\Scripts\python.exe scripts/run_combo.py data            # load + verify the frames
    .venv\Scripts\python.exe scripts/run_combo.py run --stage 1   # in-sample only
    .venv\Scripts\python.exe scripts/run_combo.py run --stage 2a,3a,3b,4a,4b,5a,5b,6
    .venv\Scripts\python.exe scripts/run_combo.py run --stage 7,8a
    .venv\Scripts\python.exe scripts/run_combo.py sample --arm a1_fractal_15m_long
    .venv\Scripts\python.exe scripts/run_combo.py run --oos b3_1h_long
    .venv\Scripts\python.exe scripts/run_combo.py --symbol XAUUSD run --stage 1

Spec and results: docs/SETUP_COMBOS.md. Simulator: copilot/backtest/combo.py.

The held-out year stays sealed. `run --stage N` cuts every frame at the split
before anything is simulated, so the out-of-sample trades are not even computed.
`--oos` takes explicit arm names and is meant to be used once, at the very end,
for at most five arms chosen by a rule fixed in advance (in-sample interval
above zero on at least 30 trades).

A stage is at most 20 arms (RESEARCH_PROTOCOL §7); an arm is chain x pool x
timeframe x side. All five timeframes run in stage 1 only. Stage 1 then drops
every timeframe whose median cost per trade exceeds 0.5R — a rule on costs, set
before any result was seen — and later stages run on what is left.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from copilot.backtest.combo import (  # noqa: E402
    FLOW_CHAINS, ComboParams, FlowStreams, flow_streams, release_bias, simulate,
)
from copilot.backtest.report import bootstrap_expectancy_ci  # noqa: E402
from copilot.data.base import TF_MINUTES  # noqa: E402
from copilot.data.binance import fetch_ohlcv_batched  # noqa: E402
from copilot.data.cache import BatchedOHLCStore  # noqa: E402
from copilot.data.dukascopy import DukascopySource  # noqa: E402
from copilot.journal.record import session_from_ts  # noqa: E402

# The ORB window, so the two studies read the same three years.
_START = pd.Timestamp("2023-09-14", tz="UTC")
_SPLIT = pd.Timestamp("2025-09-14", tz="UTC")
_END = pd.Timestamp("2026-09-14", tz="UTC")
_IS_MONTHS = 24.0
_OOS_MONTHS = 12.0
_MIN_TRADES = 30
_MAX_COST_R = 0.5            # the timeframe cull, on stage 1's median cost per trade
_CONTROL_MIN, _CONTROL_MAX = 3000, 20000     # random-entry draws per arm
_KYIV = "Europe/Kyiv"
_OUT = Path(__file__).resolve().parent.parent / "research" / "runs"

TFS = ("3m", "5m", "15m", "30m", "1h")
SIDES = ("long", "short")
_SOURCE = "binance_futures"
_SYMBOL = "BTCUSDT"
_WARMUP = pd.Timestamp("2023-04-13", tz="UTC")      # where the cached BTC 5m history starts


@dataclass(frozen=True)
class Instrument:
    symbol: str
    prefix: str            # result files are {prefix}_stage{N}.json
    label: str
    cost_text: str
    costs: dict            # ComboParams fields that carry the cost model
    two_prices: bool       # a bid chart with a quoted ask alongside


INSTRUMENTS = {
    "BTCUSDT": Instrument("BTCUSDT", "combo", "BTCUSDT.P", "6 bps на сторону", {}, False),
    # The trader's forex.com account (2026-10-06): a floating spread of about 20
    # points, i.e. 0.20 in price, and 5 USD per 100 oz lot — read as per side,
    # so 0.10 per ounce for the round trip. The frames are Dukascopy's bid chart;
    # its own quoted spread (about three times wider) is run as a sensitivity.
    "XAUUSD": Instrument("XAUUSD", "combo_xau", "XAUUSD спот", "спред 0.20, комиссия 0.10 за круг",
                         {"cost_bps": 0.0, "cost_abs": 0.10, "spread": 0.20}, True),
}
_INSTR = INSTRUMENTS["BTCUSDT"]


@dataclass(frozen=True)
class Arm:
    name: str
    tf: str
    params: ComboParams
    htf: str | None = None        # trade only with the order flow of this timeframe


# ── Data ────────────────────────────────────────────────────────────────────

def _base_5m() -> pd.DataFrame:
    """The cached 5m history, read straight from the store — no request is made.

    `fetch_ohlcv_batched` REPLACES the stored frame when asked for a window that
    does not overlap it, so a careless recent-only pull would wipe three years.
    Reading the parquet cannot.
    """
    loaded = BatchedOHLCStore().load(_SOURCE, _SYMBOL, "5m")
    if loaded is None:
        raise RuntimeError("no cached 5m history; run scripts/run_orb.py sweep first")
    df = loaded[0]
    if df.index[-1] < _END - pd.Timedelta(minutes=5) or df.index[0] > _START - pd.Timedelta(days=90):
        raise RuntimeError(f"5m cache covers {df.index[0]} .. {df.index[-1]}, need "
                           f"{_START - pd.Timedelta(days=90)} .. {_END}")
    return df[df.index < _END]


def _resample(df5: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Aggregate 5m bars to `tf`. Buckets missing a 5m bar are dropped."""
    per = TF_MINUTES[tf] // 5
    g = df5.resample(f"{TF_MINUTES[tf]}min", label="left", closed="left")
    out = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    out = out[g["close"].count() == per]
    out.index.name = df5.index.name
    return out


def _load_3m(start: pd.Timestamp, chunk: int = 90_000) -> pd.DataFrame:
    """Walk back in chunks under `fetch_ohlcv_batched`'s 100k-bar cap.

    Consecutive chunks share their edge bar, so the coverage store grows as one
    contiguous frame (`run_orb.load_history`, for 3m).
    """
    frames = []
    cursor = _END
    while cursor > start:
        part = fetch_ohlcv_batched(_SYMBOL, "3m", chunk, end_ms=int(cursor.value // 1_000_000))
        if part.empty or part.index[0] >= cursor:
            break
        frames.append(part)
        cursor = part.index[0]
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[(df.index >= start) & (df.index < _END)]


_FRAMES: dict[tuple[str, str], pd.DataFrame] = {}
_SPREADS: dict[str, np.ndarray] = {}


def frame(tf: str) -> pd.DataFrame:
    key = (_INSTR.symbol, tf)
    if key not in _FRAMES:
        if _INSTR.two_prices:
            # Offline, bid side. Bars above 1h are anchored to 17:00 New York.
            _FRAMES[key] = DukascopySource().history(_INSTR.symbol, tf, _WARMUP, _END)
        else:
            base = _base_5m()
            if tf == "5m":
                _FRAMES[key] = base
            elif tf == "3m":
                _FRAMES[key] = _load_3m(base.index[0])
            else:
                _FRAMES[key] = _resample(base, tf)
    return _FRAMES[key]


def quoted_spread(tf: str) -> np.ndarray:
    """Ask minus bid at each bar's close, as the data vendor quoted it."""
    if tf not in _SPREADS:
        bid = frame(tf)
        ask = DukascopySource().history(_INSTR.symbol, tf, _WARMUP, _END, side="ask")
        gap = (ask["close"].reindex(bid.index).ffill() - bid["close"]).clip(lower=0.0)
        _SPREADS[tf] = gap.fillna(gap.median()).to_numpy(np.float64)
    return _SPREADS[tf]


def data() -> int:
    """Load every frame, report coverage and gaps, check the resample against
    the 30m and 1h klines Binance itself served (still on disk from earlier runs)."""
    if _INSTR.two_prices:
        for tf in TFS:
            df = frame(tf)
            print(f"{tf:>4}: {len(df):7d} баров  {df.index[0]} .. {df.index[-1]}")
        print("календарь и сверка ресемпла: scripts/measure_xau.py calendar | verify")
        return 0
    ok = True
    for tf in TFS:
        df = frame(tf)
        step = pd.Timedelta(minutes=TF_MINUTES[tf])
        gaps = int((df.index.to_series().diff().dropna() != step).sum())
        print(f"{tf:>4}: {len(df):7d} баров  {df.index[0]} .. {df.index[-1]}  разрывов: {gaps}")
        ok &= gaps == 0 and df.index[0] <= _START - pd.Timedelta(days=90)
    cache_dir = BatchedOHLCStore()._dir
    for tf in ("30m", "1h"):
        files = sorted(cache_dir.glob(f"{_SOURCE}_{_SYMBOL}_{tf}_*.parquet"),
                       key=lambda f: f.stat().st_size, reverse=True)
        if not files:
            print(f"{tf}: нет файла Binance для сверки")
            continue
        ref = pd.read_parquet(files[0])
        if ref.index.tz is None:
            ref.index = ref.index.tz_localize("UTC")
        mine = frame(tf)
        both = mine.index.intersection(ref.index)
        cols = ["open", "high", "low", "close"]
        diff = (mine.loc[both, cols] - ref.loc[both, cols]).abs().to_numpy()
        bad = both[(diff > 1e-9).any(axis=1)]
        print(f"{tf}: ресемпл против Binance — общих баров {len(both)}, расхождений {len(bad)}"
              + (f": {[str(ts) for ts in bad]}" if len(bad) else ""))
        # Binance's own klines disagree across timeframes on a handful of bars
        # (2023-11-10 15:00, 2024-10-28 20:00-21:30: the 30m/1h kline is cut
        # short against its 5m parts). A resample bug would hit every bar.
        ok &= len(bad) <= len(both) * 0.001 and len(both) > 1000
    print("данные в порядке" if ok else "ЕСТЬ ПРОБЛЕМЫ С ДАННЫМИ")
    return 0 if ok else 1


# ── Stages ──────────────────────────────────────────────────────────────────

_SWEEP_CHAINS = ("A1", "A2", "A3", "A4", "A5")


def _arms(chain: str, tfs: tuple[str, ...], pool: str = "fractal") -> list[Arm]:
    """One arm per timeframe and side. Only the sweep chains have a pool, so only
    their names carry it."""
    tag = f"{chain.lower()}_{pool}" if chain in _SWEEP_CHAINS else chain.lower()
    return [Arm(f"{tag}_{tf}_{side}", tf,
                ComboParams(chain=chain, pool=pool, side=side, **_INSTR.costs))
            for tf in tfs for side in SIDES]


def kept_tfs() -> tuple[str, ...]:
    path = _OUT / f"{_INSTR.prefix}_stage1.json"
    if not path.exists():
        raise RuntimeError("stage 1 has not been run: the timeframe cull comes from it")
    return tuple(json.loads(path.read_text(encoding="utf-8"))["tf_cull"]["kept"])


# Every stage after the first runs on the timeframes stage 1 kept. With four of
# them an arm pair costs 8 arms, so a stage holds two chains at most.
_STAGES: dict[str, list[tuple[str, str]]] = {
    "2a": [("A1", "prev_day")],
    "2b": [("A1", "session")],
    "3a": [("A2", "fractal"), ("A3", "fractal")],
    "3b": [("A5", "fractal"), ("A4", "fractal")],
    "4a": [("B1", "fractal"), ("B3", "fractal")],
    "4b": [("C0", "fractal"), ("C1", "fractal")],
    "5a": [("B2", "fractal"), ("B4", "fractal")],
    "5b": [("C2", "fractal")],
    "6": [("C3", "fractal"), ("C4", "fractal")],
}
STAGES = ("1", *_STAGES, "7", "8a", "8b")


def _results(stages: tuple[str, ...]) -> list[dict]:
    rows = []
    for stage in stages:
        path = _OUT / f"{_INSTR.prefix}_stage{stage}.json"
        if not path.exists():
            raise RuntimeError(f"stage {stage} has not been run")
        rows += json.loads(path.read_text(encoding="utf-8"))["arms"]
    return rows


_STAGE7_FROM = ("1", "2a", "3a", "3b", "4a", "4b", "5a", "5b", "6")
_STAGE7_VARIANTS = {"ce": {"entry": "ce"}, "tp15": {"tp_r": 1.5}, "tp30": {"tp_r": 3.0}}


def _stage7_arms() -> list[Arm]:
    """Three variants of the five arms with the highest in-sample lower bound.

    Eligible: at least 30 trades and an interval not wholly below zero. The
    rule was written before the stage was run; it selects on results, so this
    stage adds to the multiple-testing burden rather than relieving it.
    """
    known = {a.name: a for st in _STAGE7_FROM for a in stage_arms(st)}
    rows = [r for r in _results(_STAGE7_FROM)
            if r["stats"]["n"] >= _MIN_TRADES and r["stats"]["mean_r_ci"][1] >= 0]
    rows.sort(key=lambda r: -r["stats"]["mean_r_ci"][0])
    out = []
    for row in rows[:5]:
        base = known[row["name"]]
        for tag, change in _STAGE7_VARIANTS.items():
            out.append(Arm(f"{base.name}__{tag}", base.tf, replace(base.params, **change)))
    return out


def _stage8a_arms() -> list[Arm]:
    """The trader's example with a higher-timeframe bias: the setup must agree
    with the order flow of 1h or 4h. A 1h arm takes the 4h bias only."""
    out = []
    for tf in kept_tfs():
        for htf in ("1h", "4h"):
            if TF_MINUTES[htf] <= TF_MINUTES[tf]:
                continue
            out += [Arm(f"{a.name}__htf{htf}", a.tf, a.params, htf) for a in _arms("A1", (tf,))]
    return out


def _stage8b_arms() -> list[Arm]:
    """Stage 8a plus the other half of the trader's \"complex variant\": the
    target is the nearest unbroken fractal of the same higher timeframe, and a
    setup paying less than 1.8R to it is skipped."""
    return [Arm(f"{a.name}_tgt", a.tf, replace(a.params, target="htf_fractal"), a.htf)
            for a in _stage8a_arms()]


def stage_arms(stage: str) -> list[Arm]:
    if stage == "1":
        return _arms("A1", TFS)
    if stage == "7":
        return _stage7_arms()
    if stage == "8a":
        return _stage8a_arms()
    if stage == "8b":
        return _stage8b_arms()
    if stage not in _STAGES:
        raise ValueError(f"stage {stage!r} is not defined")
    tfs = kept_tfs()
    return [arm for chain, pool in _STAGES[stage] for arm in _arms(chain, tfs, pool)]


def all_arms() -> dict[str, Arm]:
    out: dict[str, Arm] = {}
    for stage in STAGES:
        try:
            out.update({a.name: a for a in stage_arms(stage)})
        except RuntimeError:
            pass
    return out


# ── Statistics ──────────────────────────────────────────────────────────────

def _ci(values: pd.Series) -> list[float]:
    return list(bootstrap_expectancy_ci(values.tolist()))


def _maker_cost_r(t: pd.DataFrame) -> pd.Series:
    """Limit entry and limit target as maker (2 bps, no slippage); the stop stays
    a taker order with slippage (6 bps). Optimistic: a touch does not guarantee a
    maker fill."""
    risk = (t["entry"] - t["stop"]).abs()
    exit_bps = np.where(t["exit_kind"] == "tp", 2.0, 6.0)
    return (t["entry"] * 2.0 + t["exit"] * exit_bps) / 10_000 / risk


def _stats(trades: pd.DataFrame, months: float) -> dict:
    t = trades[trades["closed"]]
    out = {"n": int(len(t)), "unfinished": int((~trades["closed"]).sum())}
    if t.empty:
        return out
    r = t["r"]
    gain, loss = r[r > 0].sum(), -r[r < 0].sum()
    out.update({
        "per_month": round(len(t) / months, 1),
        "winrate": round(float((t["exit_kind"] == "tp").mean()), 4),
        "mean_r": round(float(r.mean()), 3),
        "mean_r_ci": _ci(r),
        "pf": round(float(gain / loss), 3) if loss > 0 else None,
        "gross_r": round(float(t["gross_r"].mean()), 3),
        "gross_r_ci": _ci(t["gross_r"]),
        "median_risk_pct": round(float(t["risk_pct"].median()), 4),
        "median_risk_atr": round(float(t["risk_atr"].median()), 3),
        # Commission plus what the spread is worth: the spread is not charged (it
        # is in the fills), but it is a cost of the round trip all the same.
        "median_cost_r": round(float((t["cost_r"] + t["spread_r"]).median()), 3),
        "floor_share": round(float(t["floor_hit"].mean()), 4),
    })
    if not _INSTR.two_prices:
        # A fee schedule in bps of notional; it says nothing about a spread instrument.
        maker = t["gross_r"] - _maker_cost_r(t)
        out.update(maker_r=round(float(maker.mean()), 3), maker_r_ci=_ci(maker))
    return out


def _verdict(s: dict) -> str:
    if s["n"] < _MIN_TRADES:
        return "мало сделок"
    lo, hi = s["mean_r_ci"]
    if lo > 0:
        return "ЭДЖ на IS"
    if hi < 0:
        return "убыточна"
    return "неотличима от нуля"


def _split_stats(t: pd.DataFrame, key: pd.Series) -> dict:
    out = {}
    closed = t[t["closed"]]
    for label, part in closed.groupby(key[closed.index]):
        out[str(label)] = {"n": int(len(part)), "mean_r": round(float(part["r"].mean()), 3),
                           "mean_r_ci": _ci(part["r"]) if len(part) >= _MIN_TRADES else None}
    return out


_FLOW: dict[str, FlowStreams] = {}


def flow(tf: str, n: int) -> FlowStreams:
    """Order-flow streams for the first `n` bars of a timeframe.

    One causal pass over the full frame, cached, then cut: the walk only
    appends, so the prefix of the full pass IS the pass over the prefix
    (`test_flow_streams_only_append`). The held-out year's events are dropped by
    the cut before any chain sees them.
    """
    if tf not in _FLOW:
        _FLOW[tf] = flow_streams(frame(tf))
    return _FLOW[tf].cut(n)


_HTF_EVENTS: dict[str, tuple[pd.DatetimeIndex, np.ndarray]] = {}


def htf_bias(htf: str, index: pd.DatetimeIndex, tf: str) -> np.ndarray:
    """Order-flow direction of `htf` as of each bar's close on `index` (+1/-1/0).

    The events come from the full frame; the walk only appends, and a cut index
    simply never reaches the later ones. `release_bias` holds each break back
    until the candle that made it has closed.
    """
    if htf not in _HTF_EVENTS:
        full = frame(htf)
        fs = flow_streams(full)
        _HTF_EVENTS[htf] = (full.index[fs.break_i], fs.direction)
    opens, direction = _HTF_EVENTS[htf]
    return release_bias(opens, direction, TF_MINUTES[htf], index, TF_MINUTES[tf])


def _diagnostics(arm: Arm, t: pd.DataFrame, fl: FlowStreams | None) -> dict:
    if t.empty:
        return {}
    session = t["entry_ts"].map(lambda ts: session_from_ts(ts.isoformat()))
    out = {"by_session": _split_stats(t, session)}
    if fl is not None:
        bias = fl.bias[t["known_i"].to_numpy()]
        want = 1 if arm.params.side == "long" else -1
        label = pd.Series(np.where(bias == want, "по потоку",
                                   np.where(bias == -want, "против потока", "нет потока")),
                          index=t.index)
        out["by_flow"] = _split_stats(t, label)
    return out


def random_control(df: pd.DataFrame, t: pd.DataFrame, params: ComboParams,
                   lo: pd.Timestamp, hi: pd.Timestamp,
                   seed: int = 20261003) -> tuple[dict, np.ndarray]:
    """The arm's own trades at random moments: market entry at a random bar's
    open, same side, each trade's own risk in percent and its own planned
    reward-to-risk, same exit rules and costs. Returns a summary and the net R of
    every draw.

    This is what the arm is measured against (RESEARCH_PROTOCOL §2.5, 2026-10-06).
    Zero is the wrong reference in a trending window: over the two in-sample
    years BTC rose 4.42x and a random 1h long with a 2R target made about +0.09R
    before costs, a random short about -0.09R.
    """
    closed = t[t["closed"]]
    if closed.empty:
        return {}, np.empty(0)
    o = df["open"].to_numpy(np.float64)
    h = df["high"].to_numpy(np.float64)
    low = df["low"].to_numpy(np.float64)
    a = int(df.index.searchsorted(lo))
    b = int(df.index.searchsorted(hi))
    rng = np.random.default_rng(seed)
    long_side = params.side == "long"
    n = len(closed)
    draws = max(1, -(-min(max(5 * n, _CONTROL_MIN), _CONTROL_MAX) // n))
    risk_pcts = np.tile(closed["risk_pct"].to_numpy(), draws)
    rrs = np.tile(((closed["tp"] - closed["entry"]).abs() / (closed["entry"] - closed["stop"]).abs()).to_numpy(), draws)
    gross, net = [], []
    # The side that buys pays the spread: a long on the way in (it buys at the
    # ask), a short on the way out (its stop and target trade at the ask).
    spread = params.spread
    for risk_pct, rr in zip(risk_pcts, rrs):
        i = int(rng.integers(a, b))
        entry = o[i] + spread if long_side else o[i]
        risk = entry * risk_pct / 100.0
        stop = entry - risk if long_side else entry + risk
        tp = entry + rr * risk if long_side else entry - rr * risk
        j, step, exit_px = i, 256, None
        while j < b and exit_px is None:
            k = min(b, j + step)
            if long_side:
                hit_sl = low[j:k] <= stop
                hit_tp = h[j:k] >= tp
            else:
                hit_sl = h[j:k] >= stop - spread
                hit_tp = low[j:k] <= tp - spread
            hit = np.flatnonzero(hit_sl | hit_tp)
            if len(hit):
                exit_px = stop if hit_sl[hit[0]] else tp          # stop wins a shared bar
            j, step = k, step * 2
        if exit_px is None:
            continue
        g = (exit_px - entry) / risk * (1 if long_side else -1)
        gross.append(g)
        net.append(g - ((entry + exit_px) * params.cost_bps / 10_000 + params.cost_abs) / risk)
    if not gross:
        return {}, np.empty(0)
    summary = {"n": len(gross), "gross_r": round(float(np.mean(gross)), 3),
               "net_r": round(float(np.mean(net)), 3)}
    return summary, np.array(net)


def excess_ci(arm: np.ndarray, control: np.ndarray, iterations: int = 2000,
              seed: int = 20260823) -> list[float]:
    """Percentile bootstrap interval for mean(arm) - mean(control), the two
    samples resampled independently. Fixed seed: a rerun reports the same
    interval."""
    rng = np.random.default_rng(seed)
    diffs = np.empty(iterations)
    for k in range(iterations):
        diffs[k] = (arm[rng.integers(0, len(arm), len(arm))].mean()
                    - control[rng.integers(0, len(control), len(control))].mean())
    return [round(float(np.percentile(diffs, 2.5)), 3), round(float(np.percentile(diffs, 97.5)), 3)]


def _verdict_vs_control(s: dict) -> str:
    if s["n"] < _MIN_TRADES or "excess_r_ci" not in s:
        return "мало сделок"
    lo, hi = s["excess_r_ci"]
    if lo > 0:
        return "ЭДЖ" if s["mean_r"] > 0 else "лучше случайного, но в минусе"
    if hi < 0:
        return "хуже случайного"
    return "неотличима от случайного"


# ── Running ─────────────────────────────────────────────────────────────────

def run_arm(arm: Arm, oos: bool = False, with_flow: bool = True) -> dict:
    t0 = time.time()
    full = frame(arm.tf)
    if oos:
        df, lo, hi, months = full, _SPLIT, _END, _OOS_MONTHS
    else:
        df, lo, hi, months = full[full.index < _SPLIT], _START, _SPLIT, _IS_MONTHS
    need_flow = with_flow or arm.params.chain in FLOW_CHAINS
    fl = flow(arm.tf, len(df)) if need_flow else None
    gate = None
    if arm.htf is not None:
        gate = htf_bias(arm.htf, df.index, arm.tf) == (1 if arm.params.side == "long" else -1)
    htf = None
    if arm.params.target == "htf_fractal":
        hdf = frame(arm.htf)
        htf = (hdf[hdf.index <= df.index[-1]], TF_MINUTES[arm.htf], TF_MINUTES[arm.tf])
    res = simulate(df, arm.params, fl, gate, htf)
    t = res.trades
    t = t[(t["known_ts"] >= lo) & (t["known_ts"] < hi)].reset_index(drop=True)
    stats = _stats(t, months)
    control, control_net = random_control(df, t, arm.params, lo, hi)
    if control:
        arm_net = t.loc[t["closed"], "r"].to_numpy()
        stats["excess_r"] = round(float(arm_net.mean() - control_net.mean()), 3)
        stats["excess_r_ci"] = excess_ci(arm_net, control_net)
    quoted = None
    if _INSTR.two_prices:
        # Same arm, fills under the spread Dukascopy actually quoted on each bar
        # instead of the account's constant one. A reading, not another arm.
        q = simulate(df, arm.params, fl, gate, htf, spread=quoted_spread(arm.tf)[:len(df)]).trades
        q = q[(q["known_ts"] >= lo) & (q["known_ts"] < hi) & q["closed"]]
        quoted = {"n": int(len(q))}
        if len(q):
            quoted.update(mean_r=round(float(q["r"].mean()), 3), mean_r_ci=_ci(q["r"]),
                          median_spread_r=round(float(q["spread_r"].median()), 3))
    row = {
        "name": arm.name, "tf": arm.tf, "side": arm.params.side, "htf": arm.htf,
        "quoted_spread": quoted,
        "window": "OOS" if oos else "IS", "params": asdict(arm.params),
        "funnel_whole_frame": res.funnel, "stats": stats, "verdict": _verdict(stats),
        "verdict_control": _verdict_vs_control(stats),
        **_diagnostics(arm, t, fl),
        "control": control,
        "seconds": round(time.time() - t0, 1),
    }
    return row


def _fmt(row: dict) -> str:
    s = row["stats"]
    if not s["n"]:
        return f"  {row['name']:30} нет сделок"
    c = row["control"]
    return (f"  {row['name']:30} n={s['n']:5} ({s['per_month']:6.1f}/мес)  WR {s['winrate']:.1%}  "
            f"E {s['mean_r']:+.3f}R {s['mean_r_ci']}  |  случайный вход {c['net_r']:+.3f}R  "
            f"сверх него {s['excess_r']:+.3f}R {s['excess_r_ci']}  |  без издержек {s['gross_r']:+.3f}R  "
            f"стоп {s['median_risk_atr']:.2f} ATR  издержки {s['median_cost_r']:.2f}R  "
            f"пол {s['floor_share']:.0%}  |  {row['verdict_control']}  (к нулю: {row['verdict']})")


def _tf_cull(rows: list[dict]) -> dict:
    """Median cost per trade by timeframe, both sides pooled, weighted by trades."""
    cost = {}
    for tf in TFS:
        parts = [(r["stats"]["median_cost_r"], r["stats"]["n"]) for r in rows
                 if r["tf"] == tf and r["stats"]["n"]]
        if parts:
            cost[tf] = round(sum(c * n for c, n in parts) / sum(n for _, n in parts), 3)
    kept = [tf for tf in TFS if tf in cost and cost[tf] <= _MAX_COST_R]
    return {"rule": f"median cost per trade <= {_MAX_COST_R}R", "cost_r": cost, "kept": kept,
            "dropped": [tf for tf in TFS if tf not in kept]}


def run(stage: str | None, only: str | None, oos: str | None, with_flow: bool) -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    if oos:
        known = all_arms()
        names = [n.strip() for n in oos.split(",")]
        missing = [n for n in names if n not in known]
        if missing:
            raise SystemExit(f"неизвестные армы: {missing}")
        if len(names) > 5:
            raise SystemExit("в OOS идёт не больше 5 арм")
        arms, out_path, is_oos = [known[n] for n in names], _OUT / f"{_INSTR.prefix}_oos.json", True
    else:
        arms = stage_arms(stage)
        if only:
            wanted = {n.strip() for n in only.split(",")}
            arms = [a for a in arms if a.name in wanted]
        out_path, is_oos = _OUT / f"{_INSTR.prefix}_stage{stage}.json", False
    assert len(arms) <= 20, "a stage is at most 20 arms (RESEARCH_PROTOCOL §7)"

    window = f"{_SPLIT.date()} .. {_END.date()} (OOS)" if is_oos else f"{_START.date()} .. {_SPLIT.date()} (IS)"
    print(f"{_INSTR.label}: {len(arms)} арм, окно {window}, издержки: {_INSTR.cost_text}")
    rows: list[dict] = []
    for arm in arms:
        row = run_arm(arm, oos=is_oos, with_flow=with_flow)
        rows.append(row)
        print(_fmt(row), flush=True)
        payload = {"symbol": _INSTR.symbol, "stage": stage, "window": window,
                   "costs": _INSTR.cost_text, "arms": rows}
        if stage == "1" and not only and not is_oos:
            payload["tf_cull"] = _tf_cull(rows)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str),
                            encoding="utf-8")
    if stage == "1" and not only and not is_oos:
        cull = _tf_cull(rows)
        print(f"\nОтсев ТФ ({cull['rule']}): издержки {cull['cost_r']}")
        print(f"  остаются {cull['kept']}, выбывают {cull['dropped']}")
    print(f"\n→ {out_path}")
    return 0


def sample(arm_name: str, count: int, seed: int, since: str | None = None) -> int:
    """Random in-sample trades of one arm, in Kyiv time, to check on a chart.
    `since` keeps only trades from that date on — chart history is finite."""
    arm = all_arms()[arm_name]
    df = frame(arm.tf)
    df = df[df.index < _SPLIT]
    fl = flow(arm.tf, len(df)) if arm.params.chain in FLOW_CHAINS else None
    t = simulate(df, arm.params, fl).trades
    floor = max(_START, pd.Timestamp(since, tz="UTC")) if since else _START
    t = t[(t["known_ts"] >= floor) & t["closed"]]
    pick = t.sample(n=min(count, len(t)), random_state=seed).sort_values("entry_ts")
    kyiv = lambda ts: ts.tz_convert(_KYIV).strftime("%d.%m.%Y %H:%M")  # noqa: E731
    print(f"{arm_name}: {len(pick)} из {len(t)} сделок IS, {_INSTR.label} {arm.tf}, время Киев")
    for _, r in pick.iterrows():
        print(f"  триггер {kyiv(r['trigger_ts'])}  сетап на закрытии свечи {kyiv(r['known_ts'])}  "
              f"вход {kyiv(r['entry_ts'])} @ {r['entry']:.1f}  стоп {r['stop']:.1f}  "
              f"тейк {r['tp']:.1f}  выход {kyiv(r['exit_ts'])} {r['exit_kind']}  {r['r']:+.2f}R")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="BTCUSDT", choices=sorted(INSTRUMENTS))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("data")
    r = sub.add_parser("run")
    r.add_argument("--stage", help="one stage or a comma-separated list: " + ", ".join(STAGES))
    r.add_argument("--only", help="comma-separated arm names within the stage")
    r.add_argument("--oos", help="comma-separated arm names; opens the held-out year")
    r.add_argument("--no-flow", action="store_true", help="skip the order-flow split")
    s = sub.add_parser("sample")
    s.add_argument("--arm", required=True)
    s.add_argument("--count", type=int, default=10)
    s.add_argument("--seed", type=int, default=20261003)
    s.add_argument("--since", help="YYYY-MM-DD: only trades from this date (still in-sample)")
    args = ap.parse_args()
    global _INSTR
    _INSTR = INSTRUMENTS[args.symbol]
    if args.cmd == "data":
        return data()
    if args.cmd == "sample":
        return sample(args.arm, args.count, args.seed, args.since)
    if not args.stage and not args.oos:
        ap.error("run needs --stage or --oos")
    if args.oos:
        return run(None, None, args.oos, with_flow=not args.no_flow)
    for stage in args.stage.split(","):
        print(f"\n══ этап {stage} ══")
        run(stage.strip(), args.only, None, with_flow=not args.no_flow)
    return 0


if __name__ == "__main__":
    sys.exit(main())
