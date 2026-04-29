"""
Volume Profile (VP) detector — OHLCV approximation.

Distributes each bar's volume across its [low, high] price range using a
triangular distribution peaked at the close price, then identifies:
  - POC  : bucket with the highest volume (Point of Control)
  - VA   : Value Area — smallest set of buckets covering 70% of volume
  - HVN  : High Volume Nodes — local volume peaks (price acceptance zones)
  - LVN  : Low Volume Nodes — local volume troughs (price rejection zones)

The triangular distribution weights volume toward the close, improving POC
accuracy over the naive uniform-overlap approach.
"""

from __future__ import annotations

import pandas as pd

TOOL_SCHEMA = {
    "name": "detect_volume_profile",
    "description": (
        "Approximate Volume Profile from OHLCV: distribute each bar's volume "
        "across its price range to find HVN (High Volume Nodes, acceptance) "
        "and LVN (Low Volume Nodes, rejection / fast-move zones). "
        "Use to assess POI quality — an OB sitting inside an HVN has stronger "
        "structural support; an LVN between entry and target means price will "
        "move through that gap quickly."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "e.g. BTCUSDT"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "1h", "4h", "1d"],
            },
            "bars": {
                "type": "integer",
                "default": 200,
                "description": "Number of bars to include in the profile",
            },
            "session_bars": {
                "type": "integer",
                "description": (
                    "If set, use only the last N bars (session window). "
                    "Useful for an intraday profile vs a longer composite."
                ),
            },
            "resolution_pct": {
                "type": "number",
                "default": 0.1,
                "description": "Price bucket width as % of current price (default 0.1%)",
            },
        },
        "required": ["symbol", "timeframe"],
    },
}


def _triangular_weight(low: float, high: float, close: float, blo: float, bhi: float) -> float:
    """
    Fraction of a triangular PDF on [low, high] peaked at close that falls
    within [blo, bhi].  Returns a value in [0, 1]; the caller multiplies by volume.
    """
    span = high - low
    if span < 1e-12:
        return 1.0 if blo <= low <= bhi else 0.0

    # Clamp peak to [low, high]
    c = max(low, min(high, close))

    # Intersect bucket with bar range
    lo = max(blo, low)
    hi = min(bhi, high)
    if hi <= lo:
        return 0.0

    def _cdf(x: float) -> float:
        """CDF of triangular distribution at x (clamped to [low, high])."""
        x = max(low, min(high, x))
        if x <= c:
            # Rising side: F(x) = (x - low)^2 / (span * (c - low)) if c > low else 0
            base = c - low
            return ((x - low) ** 2 / (span * base)) if base > 1e-12 else 0.0
        else:
            # Falling side: F(x) = 1 - (high - x)^2 / (span * (high - c))
            base = high - c
            return (1.0 - (high - x) ** 2 / (span * base)) if base > 1e-12 else 1.0

    return max(0.0, _cdf(hi) - _cdf(lo))


def detect_volume_profile(
    df: pd.DataFrame,
    resolution_pct: float = 0.1,
    session_bars: int | None = None,
) -> dict:
    if len(df) < 10:
        return {"status": "insufficient_data", "needed": 10, "got": len(df)}

    ohlcv = df.iloc[-session_bars:] if session_bars and session_bars < len(df) else df
    if len(ohlcv) < 5:
        return {"status": "insufficient_data", "needed": 5, "got": len(ohlcv)}

    price_low = float(ohlcv["low"].min())
    price_high = float(ohlcv["high"].max())
    current_price = float(ohlcv["close"].iloc[-1])

    if price_high - price_low < 1e-8:
        return {"status": "flat_market", "reason": "price range too narrow to build a profile"}

    # Build buckets
    bucket_width = max(current_price * resolution_pct / 100.0, 1e-8)
    n_buckets = min(max(20, int((price_high - price_low) / bucket_width) + 1), 500)
    bucket_width = (price_high - price_low) / n_buckets  # recompute after cap

    volumes = [0.0] * n_buckets

    for _, row in ohlcv.iterrows():
        bar_lo = float(row["low"])
        bar_hi = float(row["high"])
        bar_cl = float(row["close"])
        bar_vol = float(row["volume"])
        bar_range = bar_hi - bar_lo

        if bar_range < 1e-10:
            idx = max(0, min(int((bar_lo - price_low) / bucket_width), n_buckets - 1))
            volumes[idx] += bar_vol
            continue

        b_start = max(0, int((bar_lo - price_low) / bucket_width))
        b_end = min(n_buckets - 1, int((bar_hi - price_low) / bucket_width))

        for b in range(b_start, b_end + 1):
            bkt_lo = price_low + b * bucket_width
            bkt_hi = bkt_lo + bucket_width
            weight = _triangular_weight(bar_lo, bar_hi, bar_cl, bkt_lo, bkt_hi)
            if weight > 0:
                volumes[b] += bar_vol * weight

    total_vol = sum(volumes)
    if total_vol < 1e-10:
        return {"status": "no_volume", "reason": "all bars have zero volume"}

    # POC
    poc_idx = volumes.index(max(volumes))
    poc_price = round(price_low + (poc_idx + 0.5) * bucket_width, 2)

    # Value Area (70%)
    val_idx, vah_idx = _expand_value_area(volumes, poc_idx, total_vol * 0.70)
    vah = round(price_low + (vah_idx + 1) * bucket_width, 2)
    val = round(price_low + val_idx * bucket_width, 2)

    # HVN / LVN thresholds (mean ± 1σ)
    vol_series = pd.Series(volumes)
    vol_mean = float(vol_series.mean())
    vol_std = float(vol_series.std())
    hvn_threshold = vol_mean + vol_std
    lvn_threshold = max(0.0, vol_mean - 0.5 * vol_std)

    hvn_nodes: list[dict] = []
    lvn_nodes: list[dict] = []

    for i, vol in enumerate(volumes):
        mid = price_low + (i + 0.5) * bucket_width
        bkt_lo = price_low + i * bucket_width
        bkt_hi = bkt_lo + bucket_width
        vol_pct = round(vol / total_vol * 100, 2)

        left = volumes[i - 1] if i > 0 else 0.0
        right = volumes[i + 1] if i < n_buckets - 1 else 0.0

        if vol >= hvn_threshold and vol >= left and vol >= right:
            hvn_nodes.append({
                "price_mid": round(mid, 2),
                "price_low": round(bkt_lo, 2),
                "price_high": round(bkt_hi, 2),
                "volume_pct": vol_pct,
            })

        if 0 < vol <= lvn_threshold and vol <= left and vol <= right:
            lvn_nodes.append({
                "price_mid": round(mid, 2),
                "price_low": round(bkt_lo, 2),
                "price_high": round(bkt_hi, 2),
                "volume_pct": vol_pct,
            })

    hvn_nodes = sorted(hvn_nodes, key=lambda x: -x["volume_pct"])[:10]
    lvn_nodes = sorted(lvn_nodes, key=lambda x: x["volume_pct"])[:10]

    # Current price location
    if current_price > poc_price * 1.0005:
        location = "above_poc"
    elif current_price < poc_price * 0.9995:
        location = "below_poc"
    else:
        location = "at_poc"

    atr = _atr(ohlcv, 14)

    def _dist(p: float) -> float:
        return round(abs(current_price - p) / atr, 2) if atr > 0 else 0.0

    hvn_above = _nearest(hvn_nodes, current_price, above=True)
    hvn_below = _nearest(hvn_nodes, current_price, above=False)
    lvn_above = _nearest(lvn_nodes, current_price, above=True)
    lvn_below = _nearest(lvn_nodes, current_price, above=False)

    result: dict = {
        "poc": poc_price,
        "vah": vah,
        "val": val,
        "value_area_pct": 70.0,
        "current_price": round(current_price, 2),
        "current_price_location": location,
        "hvn_nodes": hvn_nodes,
        "lvn_nodes": lvn_nodes,
    }

    if hvn_above:
        result["nearest_hvn_above"] = {**hvn_above, "distance_atr": _dist(hvn_above["price_mid"])}
    if hvn_below:
        result["nearest_hvn_below"] = {**hvn_below, "distance_atr": _dist(hvn_below["price_mid"])}
    if lvn_above:
        result["nearest_lvn_above"] = {**lvn_above, "distance_atr": _dist(lvn_above["price_mid"])}
    if lvn_below:
        result["nearest_lvn_below"] = {**lvn_below, "distance_atr": _dist(lvn_below["price_mid"])}

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _expand_value_area(
    volumes: list[float], poc_idx: int, target: float
) -> tuple[int, int]:
    lo, hi = poc_idx, poc_idx
    acc = volumes[poc_idx]
    n = len(volumes)
    while acc < target and (lo > 0 or hi < n - 1):
        up = volumes[hi + 1] if hi < n - 1 else 0.0
        dn = volumes[lo - 1] if lo > 0 else 0.0
        if up >= dn:
            hi = min(hi + 1, n - 1)
            acc += up
        else:
            lo = max(lo - 1, 0)
            acc += dn
    return lo, hi


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < 2:
        return 0.0
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    val = tr.rolling(period).mean().iloc[-1]
    return float(val) if pd.notna(val) else float(tr.mean())


def _nearest(nodes: list[dict], price: float, above: bool) -> dict | None:
    candidates = [n for n in nodes if (n["price_mid"] > price) == above]
    if not candidates:
        return None
    key = min if above else max
    return key(candidates, key=lambda n: n["price_mid"])
