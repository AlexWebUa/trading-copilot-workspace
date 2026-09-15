"""
Balance Price Range (BPR) — where a bullish and a bearish imbalance overlap.

Definition given by the trader (2026-08-26) for the 30mOF setup: "пересечение
двух имбалансов", any age. So a BPR is the price band two FVGs of OPPOSITE
polarity have in common — the market left an inefficiency in both directions
over the same prices, which makes the overlap a stronger POI than either gap.

The zone is the intersection itself, not the union: `[max(lowers), min(uppers)]`
of the two gaps. A pair that merely touches (zero-width intersection) is not a
BPR and is dropped.

Polarity: the BPR is named after the direction it is expected to support, which
is the direction of the gap formed LAST — that is the imbalance price most
recently failed to fill, and the one the trader is leaning on. A bullish BPR is
therefore a long POI.

Ages are unfiltered on purpose (trader's call): unlike the 1hIMB setup, 30mOF
does not care when the imbalance formed.
"""

import pandas as pd

from copilot.detectors.fvg import detect_fvg

TOOL_SCHEMA = {
    "name": "detect_bpr",
    "description": (
        "Find Balance Price Ranges — price bands where a bullish and a bearish "
        "Fair Value Gap overlap. A BPR is a stronger point of interest than either "
        "gap alone because price left an inefficiency in both directions over the "
        "same prices. Returns the overlap band, its polarity and how much of it "
        "price has already traded back through."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {
                "type": "string",
                "enum": ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"],
            },
            "max_results": {"type": "integer", "default": 6},
        },
        "required": ["symbol", "timeframe"],
    },
}


def _fill_pct(df: pd.DataFrame, formed_ts, upper: float, lower: float, bullish: bool) -> float:
    """How far price has traded back into the band since it formed, in percent."""
    width = upper - lower
    if width <= 0:
        return 100.0
    after = df[df.index > pd.Timestamp(formed_ts)]
    if after.empty:
        return 0.0
    if bullish:
        deepest = float(after["low"].min())
        filled = max(0.0, upper - max(deepest, lower))
    else:
        deepest = float(after["high"].max())
        filled = max(0.0, min(deepest, upper) - lower)
    return round(min(100.0, filled / width * 100.0), 1)


def detect_bpr(df: pd.DataFrame, max_results: int = 6) -> dict:
    if len(df) < 10:
        return {"status": "insufficient_data", "needed": 10, "got": len(df),
                "bprs": [], "count_active": 0}

    fvgs = detect_fvg(df).get("fvgs", [])
    if len(fvgs) < 2:
        return {"bprs": [], "count_active": 0}

    for f in fvgs:
        f["_ts"] = pd.Timestamp(f["formed_ts"])

    bulls = [f for f in fvgs if f["type"] == "bullish"]
    bears = [f for f in fvgs if f["type"] == "bearish"]

    bprs: list[dict] = []
    for a in bulls:
        for b in bears:
            lower = max(float(a["lower"]), float(b["lower"]))
            upper = min(float(a["upper"]), float(b["upper"]))
            if upper <= lower:
                continue                      # no overlap, or a single touching edge
            # The later gap decides polarity: it is the imbalance price most
            # recently failed to fill, and the side the trader leans on.
            later, earlier = (a, b) if a["_ts"] >= b["_ts"] else (b, a)
            bullish = later["type"] == "bullish"
            formed_ts = later["_ts"]
            bprs.append({
                "type": "bullish" if bullish else "bearish",
                "upper": round(upper, 2),
                "lower": round(lower, 2),
                "formed_ts": formed_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "paired_ts": earlier["_ts"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "fill_percentage": _fill_pct(df, formed_ts, upper, lower, bullish),
                "age_bars": int((df.index > formed_ts).sum()),
            })

    bprs.sort(key=lambda z: z["formed_ts"], reverse=True)
    return {
        "bprs": bprs[:max_results],
        "count_active": sum(1 for z in bprs if z["fill_percentage"] < 100.0),
    }
