"""
Order Flow (30mOF) — the trader's structural walk over 3-candle fractals.

Encoded 2026-08-26 against a two-day worked example the trader marked up bar by
bar (BTCUSDT 30m, 25-27 July 2026); every level, every fractal and both failed
confirmations were verified against live data before this was written. The
golden path is `tests/test_detectors_order_flow.py`.

Why this is not `detect_bos`: that detector wraps `smc.bos_choch`, whose own
swing detection deduplicates differently and produces a different sequence — on
the reference window it missed one of the trader's continuations entirely and
reported key levels he never marked. The rules below are his, stated exactly:

  Key points   A fractal high/low whose break confirms or ends the structure.
               Breaks are ALWAYS by candle BODY close ("закрепление телом"),
               never by wick — the 25 Jul 18:00 and 27 Jul 09:00 bars each
               pierced the key high and were correctly ignored.

  cBOS         CONTINUATION: a body close beyond the key point in the flow's
               own direction. Two of them confirm the flow.
  BOS          The STRUCTURE BREAK: a body close beyond the opposite key point.
               It ends the flow and starts a new one in the other direction.
               (This naming is the trader's, per the KB glossary; the smc
               library uses the opposite one — see smc_lib.structure_events.)

  After a break        the new key is the NEAREST fractal in that direction —
                       not the extreme of the leg. On 26 Jul the leg ran to
                       64566.0 but the key high is 64514.1 (04:00), the first
                       fractal after the break, which is why the flow then died
                       at 08:30 instead of surviving.
  The counter key      the FIRST fractal printed after the key, then frozen.
                       On 27 Jul the key high is 02:00 (65555.0) and the low
                       that ends the flow is 04:30 (64872.0), printed after it;
                       15:30 later prints a LOWER fractal low (64811.0) and is
                       correctly ignored, or the break would slip to 17:30.

The key itself moves only on a break, never on a fractal: 25 Jul 18:00 printed
a fractal high (64243.6) above the key high (64236.8) with its body closing
below, and the key correctly stayed put.

A fractal at bar j needs bar j+1 to confirm it, so the earliest bar that can
break it is j+2: bar j+1 cannot close above h[j] when h[j] > h[j+1].
"""

import pandas as pd

TOOL_SCHEMA = {
    "name": "detect_order_flow",
    "description": (
        "Track the structural Order Flow: alternating key highs and lows built from "
        "3-candle fractals, continuation events (cBOS) and the structure break (BOS) "
        "that ends the flow. Returns the current flow direction, how many "
        "continuations have confirmed it, and the live key high / key low. Use to "
        "answer 'what is the structure doing and is it still intact'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {"type": "string", "enum": ["3m", "5m", "15m", "30m", "1h", "4h", "1d"]},
            "swing_lookback": {
                "type": "integer",
                "default": 1,
                "description": "Bars each side of a fractal pivot. 1 = 3-candle (the setup's own).",
            },
            "max_events": {"type": "integer", "default": 8},
            "lookback": {
                "type": "integer",
                "default": 0,
                "description": "Bars of history to walk; 0 = all of them.",
            },
        },
        "required": ["symbol", "timeframe"],
    },
}

# Two continuations confirm a flow (trader, 2026-08-26): the opening BOS starts
# it, then cBOS #1 and #2 make it tradeable.
_CONFIRMATIONS_REQUIRED = 2


def _next_pool(
    fractals: list[tuple[int, float]],
    flow_start_bar: int,
    price: float,
    bull: bool,
) -> float | None:
    """Nearest fractal extreme that predates the flow and still lies ahead of it.

    Only pre-flow extremes count: fractals printed INSIDE the flow are the minor
    liquidity it feeds on along the way, which the trader explicitly does not
    treat as a reason to stop trading.
    """
    ahead = [
        lvl for idx, lvl in fractals
        if idx < flow_start_bar and (lvl > price if bull else lvl < price)
    ]
    if not ahead:
        return None
    return min(ahead) if bull else max(ahead)


def detect_order_flow(
    df: pd.DataFrame,
    swing_lookback: int = 1,
    max_events: int = 8,
    lookback: int = 0,
) -> dict:
    """Single forward pass — the same walk `copilot/pine/native/order_flow.pine`
    executes on the chart, so the backtest cannot disagree with what the trader
    verified visually.

    An earlier version searched forward for "the next fractal", which made the
    result depend on where the scan started: seeded on 25 Jul it reported a
    break the 22 Jul seed did not. A live reader has no forward search, so
    neither does this: a break arms a pending state, and the first fractal
    printed afterwards fixes the new key.
    """
    # The walk is O(n) and the backtest calls it once per bar, so an unbounded
    # frame makes a run O(n^2): 12 minutes per arm on a year of 30m data. The
    # trader accepts that the markup depends on where the scan starts and
    # "нормализуется со временем", so a generous warm-up window is equivalent
    # in practice — but the equivalence is measured, not assumed
    # (`test_bounded_lookback_agrees_with_full_history`).
    if lookback and len(df) > lookback:
        df = df.iloc[-lookback:]

    n = len(df)
    if n < 20:
        return {
            "status": "insufficient_data", "needed": 20, "got": n,
            "direction": None, "confirmed": False, "confirmations": 0,
            "key_high": None, "key_low": None, "events": [],
        }

    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    tss = [ts.strftime("%Y-%m-%dT%H:%M:%SZ") for ts in df.index]
    k = swing_lookback

    key_h = key_l = None          # levels
    key_hb = key_lb = None        # bar positions
    span_l = span_h = None
    span_lb = span_hb = None
    direction: str | None = None
    pend_up = pend_dn = False
    confirmations = 0
    flow_start_ts: str | None = None
    events: list[dict] = []
    pending_event: dict | None = None

    # Pool gate (trader, 2026-08-26). A flow that takes a fractal extreme which
    # existed BEFORE it started has arguably done its job — the reason for the
    # move is gone. Entries pause until price closes a body beyond the fractal
    # that did the taking. Reference: 12 Jul 2026, the flow from the 09:00 low
    # swept the 07:00 fractal high at 17:30, price entered the 17:30 imbalance,
    # and no close above 64271.9 ever came — the trade correctly never opened,
    # and price reversed.
    fractal_highs: list[tuple[int, float]] = []
    fractal_lows: list[tuple[int, float]] = []
    flow_start_bar: int | None = None
    pool_level: float | None = None
    pool_swept_bar: int | None = None
    gate_level: float | None = None
    entries_allowed = True

    for i in range(2 * k, n):
        j = i - k                 # the pivot, confirmed by bar i
        is_fh = all(
            highs[j] > highs[j - d] and highs[j] > highs[j + d] for d in range(1, k + 1)
        )
        is_fl = all(
            lows[j] < lows[j - d] and lows[j] < lows[j + d] for d in range(1, k + 1)
        )

        if is_fh:
            fractal_highs.append((j, float(highs[j])))
        if is_fl:
            fractal_lows.append((j, float(lows[j])))

        # ── pool gate ──────────────────────────────────────────────────────
        if flow_start_bar is not None:
            bull = direction == "bullish"
            if gate_level is not None:
                # Waiting for the confirmation that reopens entries.
                if (closes[i] > gate_level) if bull else (closes[i] < gate_level):
                    gate_level = None
                    pool_swept_bar = None
                    entries_allowed = True
                    pool_level = _next_pool(
                        fractal_highs if bull else fractal_lows,
                        flow_start_bar, closes[i], bull,
                    )
            elif pool_swept_bar is not None:
                # The pool is gone; the fractal that took it becomes the gate.
                if bull and is_fh and j >= pool_swept_bar:
                    gate_level = float(highs[j])
                elif not bull and is_fl and j >= pool_swept_bar:
                    gate_level = float(lows[j])
            elif pool_level is not None:
                taken = (highs[i] > pool_level) if bull else (lows[i] < pool_level)
                if taken:
                    pool_swept_bar = i
                    entries_allowed = False

        # Span extremes — what the counter key is seeded from when a break resolves.
        if is_fl and (key_hb is None or j > key_hb):
            if span_lb is None or lows[j] < span_l:
                span_l, span_lb = lows[j], j
        if is_fh and (key_lb is None or j > key_lb):
            if span_hb is None or highs[j] > span_h:
                span_h, span_hb = highs[j], j

        # A pending break is resolved by the first fractal in its own direction.
        if pend_up and is_fh:
            key_h, key_hb = highs[j], j
            if span_lb is not None:
                key_l, key_lb = span_l, span_lb
            span_l = span_lb = None
            pend_up = False
        elif pend_dn and is_fl:
            key_l, key_lb = lows[j], j
            if span_hb is not None:
                key_h, key_hb = span_h, span_hb
            span_h = span_hb = None
            pend_dn = False
        else:
            # Counter key = the FIRST fractal after the key, then frozen.
            if (direction == "bullish" and is_fl and key_hb is not None
                    and j > key_hb and (key_lb is None or key_lb < key_hb)):
                key_l, key_lb = lows[j], j
            if (direction == "bearish" and is_fh and key_lb is not None
                    and j > key_lb and (key_hb is None or key_hb < key_lb)):
                key_h, key_hb = highs[j], j

        if pending_event is not None and not pend_up and not pend_dn:
            pending_event["key_high"] = round(float(key_h), 2) if key_h is not None else None
            pending_event["key_high_ts"] = tss[key_hb] if key_hb is not None else None
            pending_event["key_low"] = round(float(key_l), 2) if key_l is not None else None
            pending_event["key_low_ts"] = tss[key_lb] if key_lb is not None else None
            pending_event = None

        # Seed before any structure exists.
        if key_h is None and is_fh:
            key_h, key_hb = highs[j], j
        if key_l is None and is_fl:
            key_l, key_lb = lows[j], j

        if pend_up or pend_dn:
            continue

        up = key_h is not None and closes[i] > key_h
        down = key_l is not None and closes[i] < key_l
        if not (up or down):
            continue

        ev_dir = "bullish" if up else "bearish"
        is_cont = direction == ev_dir
        if is_cont:
            confirmations += 1
        else:
            direction = ev_dir
            confirmations = 0
            flow_start_ts = tss[i]
            # A new flow re-arms the gate against its own pre-existing pools.
            flow_start_bar = i
            pool_swept_bar = None
            gate_level = None
            entries_allowed = True
            pool_level = _next_pool(
                fractal_highs if ev_dir == "bullish" else fractal_lows,
                i, closes[i], ev_dir == "bullish",
            )

        pending_event = {
            "type": "cBOS" if is_cont else "BOS",
            "direction": ev_dir,
            "broken_level": round(float(key_h if up else key_l), 2),
            # Where the broken key printed — a chart line runs from that bar to
            # the bar whose body closed through it.
            "broken_ts": tss[key_hb if up else key_lb],
            "break_ts": tss[i],
            "key_high": None, "key_high_ts": None,
            "key_low": None, "key_low_ts": None,
            "confirmations": confirmations,
        }
        events.append(pending_event)
        if up:
            pend_up = True
        else:
            pend_dn = True

    if not events:
        return {
            "status": "none", "direction": None, "confirmed": False,
            "confirmations": 0, "key_high": None, "key_low": None, "events": [],
        }

    return {
        "direction": direction,
        # "confirmed" is the trader's «поток валиден» — tradeable only from here.
        "confirmed": confirmations >= _CONFIRMATIONS_REQUIRED,
        "confirmations": confirmations,
        "flow_start_ts": flow_start_ts,
        "key_high": ({"price": round(float(key_h), 2), "ts": tss[key_hb]}
                     if key_h is not None else None),
        "key_low": ({"price": round(float(key_l), 2), "ts": tss[key_lb]}
                    if key_l is not None else None),
        # The trader's frequency rule: trade until the structure breaks OR until
        # the flow takes a pre-existing pool, then wait for one more confirmation.
        "entries_allowed": entries_allowed,
        "pool_level": round(pool_level, 2) if pool_level is not None else None,
        "pool_gate_level": round(gate_level, 2) if gate_level is not None else None,
        "events": list(reversed(events))[:max_events],
        "count": len(events),
    }
