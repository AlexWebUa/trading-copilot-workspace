"""
How each detector is invoked when producing Pine output.

Extracted from `scripts/debug_detectors.py`'s task table (P3, Aug 2026) so the
debug CLI and the copilot's `generate_pine_script` tool run the detectors
*identically*. Several detectors need more than the DataFrame:

  * breaker / mitigation / sponsored blocks — `lookback=bars, max_results=20`
  * fib zones                              — swing high/low from market structure
  * multi-TF alignment                     — HTF and LTF structure states
  * delta tools                            — a DataFrame with buy_vol/sell_vol/delta

Anything a runner needs beyond the DataFrame lives on `EmitContext` (the same
object the emitters take), plus the optional `RunDeps` for the two derived
inputs that require running another detector first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from copilot.detectors.absorption_poi import check_absorption_at_poi
from copilot.detectors.bos import detect_bos
from copilot.detectors.breaker_block import detect_breaker_block
from copilot.detectors.cd_divergence_structure import check_cd_divergence_at_structure
from copilot.detectors.compression import detect_compression
from copilot.detectors.cumulative_delta import detect_cumulative_delta
from copilot.detectors.fib_zones import detect_fib_zones
from copilot.detectors.fractals import detect_fractals
from copilot.detectors.fvg import detect_fvg
from copilot.detectors.ifvg import detect_ifvg
from copilot.detectors.liquidity import detect_liquidity
from copilot.detectors.market_structure import detect_market_structure
from copilot.detectors.mitigation_block import detect_mitigation_block
from copilot.detectors.multi_tf import check_multi_tf_alignment
from copilot.detectors.order_block import detect_order_block
from copilot.detectors.rejection_block import detect_rejection_block
from copilot.detectors.sessions import current_killzone
from copilot.detectors.sponsored_candle import detect_sponsored_candle
from copilot.detectors.volume_profile import detect_volume_profile
from copilot.pine.emitters import EmitContext

# HTF used for multi-TF alignment, keyed by LTF.
HTF_MAP: dict[str, str] = {
    "1m": "15m", "3m": "1h", "5m": "1h",
    "15m": "4h", "30m": "4h", "1h": "4h", "4h": "1d", "1d": "1d",
}

# Detectors that need buy_vol/sell_vol/delta columns.
NEEDS_DELTA: frozenset[str] = frozenset({
    "detect_cumulative_delta",
    "check_cd_divergence_at_structure",
})

# Detectors that need market structure computed first.
NEEDS_MS: frozenset[str] = frozenset({
    "detect_fib_zones",
    "check_multi_tf_alignment",
})

# Detectors that need a separate HTF OHLCV fetch.
NEEDS_HTF: frozenset[str] = frozenset({"check_multi_tf_alignment"})


@dataclass
class RunDeps:
    """Inputs a runner cannot derive from its own DataFrame alone.

    `df_delta` falls back to the plain DataFrame — the delta detectors then
    return their own error/empty result rather than raising, which is what the
    fail-soft convention asks for.
    """

    df_delta: pd.DataFrame | None = None
    ltf_ms: dict = field(default_factory=dict)
    htf_ms: dict = field(default_factory=dict)


def _swing_kwargs(ctx: EmitContext, explicit: bool) -> dict:
    """`swing_lookback` is passed only when the caller set it explicitly.

    Otherwise each detector keeps its own default (5 for ms/bos/ob, 3 for
    liquidity) so Pine output matches what the MCP tools return.
    """
    return {"swing_lookback": ctx.swing_lookback} if explicit else {}


def run(
    detector: str,
    ctx: EmitContext,
    deps: RunDeps | None = None,
    explicit_swing_lookback: bool = False,
) -> dict:
    """Run *detector* over `ctx.df` the way the Pine output expects it."""
    d = deps or RunDeps()
    df = ctx.df
    sl = _swing_kwargs(ctx, explicit_swing_lookback)
    df_delta = d.df_delta if d.df_delta is not None else df

    if detector == "detect_fvg":
        return detect_fvg(df)
    if detector == "detect_ifvg":
        return detect_ifvg(df)
    if detector == "detect_order_block":
        return detect_order_block(df, **sl)
    if detector == "detect_breaker_block":
        return detect_breaker_block(df, lookback=ctx.bars, max_results=20, **sl)
    if detector == "detect_rejection_block":
        return detect_rejection_block(df)
    if detector == "detect_mitigation_block":
        return detect_mitigation_block(df, lookback=ctx.bars, max_results=20, **sl)
    if detector == "detect_sponsored_candle":
        return detect_sponsored_candle(df, lookback=ctx.bars, max_results=20, **sl)
    if detector == "detect_liquidity":
        return detect_liquidity(df, **sl)
    if detector == "detect_bos":
        return detect_bos(df, max_results=30, **sl)
    if detector == "detect_market_structure":
        return detect_market_structure(df, **sl)
    if detector == "detect_volume_profile":
        return detect_volume_profile(df)
    if detector == "detect_fractals":
        return detect_fractals(df)
    if detector == "detect_fib_zones":
        ms = d.ltf_ms or detect_market_structure(df, **sl)
        return detect_fib_zones(
            df,
            swing_high=(ms.get("last_swing_high") or {}).get("price") or float(df["high"].max()),
            swing_low=(ms.get("last_swing_low") or {}).get("price") or float(df["low"].min()),
        )
    if detector == "detect_compression":
        return detect_compression(df)
    if detector == "check_absorption_at_poi":
        return check_absorption_at_poi(df)
    if detector == "detect_cumulative_delta":
        return detect_cumulative_delta(df_delta)
    if detector == "check_cd_divergence_at_structure":
        return check_cd_divergence_at_structure(df_delta)
    if detector == "current_killzone":
        return current_killzone()
    if detector == "check_multi_tf_alignment":
        ltf_ms = d.ltf_ms or detect_market_structure(df, **sl)
        htf_ms = d.htf_ms or ltf_ms
        return check_multi_tf_alignment(
            htf_state=htf_ms.get("state", "ranging"),
            ltf_state=ltf_ms.get("state", "ranging"),
            htf_timeframe=ctx.htf,
            ltf_timeframe=ctx.ltf,
        )
    raise KeyError(detector)


RUNNERS: dict[str, Callable[[EmitContext, RunDeps | None], dict]] = {
    name: (lambda ctx, deps=None, _n=name: run(_n, ctx, deps))
    for name in (
        "detect_fvg", "detect_ifvg", "detect_order_block", "detect_breaker_block",
        "detect_rejection_block", "detect_mitigation_block", "detect_sponsored_candle",
        "detect_liquidity", "detect_bos", "detect_market_structure",
        "detect_volume_profile", "detect_fractals", "detect_fib_zones",
        "detect_compression", "check_absorption_at_poi", "detect_cumulative_delta",
        "check_cd_divergence_at_structure", "current_killzone", "check_multi_tf_alignment",
    )
}
