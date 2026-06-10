"""Tests for copilot/detectors/fvg.py"""

import pandas as pd
from copilot.detectors.fvg import detect_fvg


def _make_three_consecutive_bullish_fvg_df() -> pd.DataFrame:
    """
    Multi-candle bullish impulse (bars 10-14) leaving exactly three consecutive
    bullish FVGs at bar_idx 10, 11, 12:

      FVG1 (bar_idx=10): C0.high=100, C2.low=104  → upper=104, lower=100
      FVG2 (bar_idx=11): C0.high=115, C2.low=118  → upper=118, lower=115
      FVG3 (bar_idx=12): C0.high=124, C2.low=127  → upper=127, lower=124

    All three are consecutive (bar indices differ by 1) so join_consecutive=True
    must merge them into a single zone: upper=127, lower=100.

    Bars 15-18: carefully engineered pullback that keeps lows[k+2] <= highs[k] for
    k ≥ 13, preventing any further FVG formation.
    """
    rows = []
    for _ in range(10):   # bars 0-9: neutral baseline for ATR
        rows.append({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 500.0})
    # bar 10: C0 of FVG1  (high=100.0)
    rows.append({"open": 99.5,  "high": 100.0, "low": 99.0,  "close": 99.5,  "volume":  500.0})
    # bar 11: C1/FVG1 + C0/FVG2  (high=115.0)
    rows.append({"open": 99.5,  "high": 115.0, "low": 100.5, "close": 114.5, "volume": 8000.0})
    # bar 12: C2/FVG1 (low=104>100 ✓) + C1/FVG2 + C0/FVG3  (high=124.0)
    rows.append({"open": 114.5, "high": 124.0, "low": 104.0, "close": 123.5, "volume": 8000.0})
    # bar 13: C2/FVG2 (low=118>115 ✓) + C1/FVG3
    rows.append({"open": 123.5, "high": 133.0, "low": 118.0, "close": 132.5, "volume": 8000.0})
    # bar 14: C2/FVG3 (low=127>124 ✓)
    rows.append({"open": 132.5, "high": 140.0, "low": 127.0, "close": 139.5, "volume": 8000.0})
    # bars 15-18: pullback — lows[k+2] <= highs[k] for k in {13,14,15,16}
    rows.append({"open": 139.5, "high": 141.0, "low": 133.0, "close": 136.0, "volume": 2000.0})  # low=133 ≤ high[13]=133
    rows.append({"open": 136.0, "high": 138.0, "low": 134.0, "close": 135.0, "volume": 1000.0})  # low=134 ≤ high[14]=140
    rows.append({"open": 135.0, "high": 137.0, "low": 133.0, "close": 134.0, "volume": 1000.0})  # low=133 ≤ high[15]=141
    rows.append({"open": 134.0, "high": 136.0, "low": 132.0, "close": 133.0, "volume": 1000.0})  # low=132 ≤ high[16]=138
    index = pd.date_range("2026-01-01", periods=len(rows), freq="1h", tz="UTC")
    df = pd.DataFrame(rows, index=index)
    df.index.name = "ts"
    return df[["open", "high", "low", "close", "volume"]].astype("float64")


def test_bullish_fvg_detected(fvg_bullish_df):
    result = detect_fvg(fvg_bullish_df)
    assert result["count_active"] >= 1
    fvg = next(f for f in result["fvgs"] if f["type"] == "bullish")
    assert fvg["upper"] > fvg["lower"]
    assert fvg["fill_state"] in ("untouched", "IOFED", "CE_tagged")
    # With join_consecutive=True (default) the base-row FVG at idx=19 (upper=100.5,
    # lower=99.5) merges with the main FVG at idx=20 (upper=105, lower=102).
    # Merged zone: lower=99.5, upper=105  →  both must be in the 97..110 band.
    assert 97.0 < fvg["lower"] < fvg["upper"] < 110.0


def test_bearish_fvg_detected(fvg_bearish_df):
    result = detect_fvg(fvg_bearish_df)
    assert result["count_active"] >= 1
    fvg = next(f for f in result["fvgs"] if f["type"] == "bearish")
    assert fvg["upper"] > fvg["lower"]


def test_no_fvg_in_flat_market(flat_df):
    result = detect_fvg(flat_df)
    assert result["count_active"] == 0


def test_insufficient_data(tiny_df):
    result = detect_fvg(tiny_df)
    assert result["status"] == "insufficient_data"
    assert result["count_active"] == 0


def test_filled_fvg_excluded(fvg_bullish_df):
    """Add a candle that completely fills the FVG; it should not appear in results."""
    import pandas as pd

    # Append a candle that dips to lower=98, filling any bullish FVG that sits near 102–105
    fill_candle = pd.DataFrame(
        [{"open": 108.0, "high": 109.0, "low": 98.0, "close": 100.0, "volume": 5000.0}],
        index=pd.date_range("2026-02-01", periods=1, freq="1h", tz="UTC"),
    )
    fill_candle.index.name = "ts"
    extended = pd.concat([fvg_bullish_df, fill_candle[["open", "high", "low", "close", "volume"]]])
    result = detect_fvg(extended)
    # Any FVG with lower near 102 should be filled
    unfilled = [f for f in result["fvgs"] if f["type"] == "bullish" and f["lower"] < 103]
    assert all(f["fill_state"] == "filled" or f not in result["fvgs"] for f in unfilled)


def test_return_schema(fvg_bullish_df):
    result = detect_fvg(fvg_bullish_df)
    assert "fvgs" in result
    assert "count_active" in result
    for fvg in result["fvgs"]:
        assert "type" in fvg
        assert "upper" in fvg
        assert "lower" in fvg
        assert "fill_state" in fvg
        assert "age_bars" in fvg
        assert fvg["fill_state"] in ("untouched", "IOFED", "CE_tagged", "filled")
        assert "_bar_idx" not in fvg, "internal _bar_idx field must not appear in output"


def test_consecutive_fvgs_merged():
    """
    join_consecutive=True (default): three adjacent same-direction FVGs produced by a
    multi-candle bullish impulse collapse into one merged zone — matching the behaviour
    of smc.fvg(join_consecutive=True).

    The merged zone must:
    - cover the widest boundaries (max upper / min lower of the three individuals)
    - remain active (fill_state != 'filled') because the pullback stays above lower=100
    - not expose the internal _bar_idx field in the output
    - preserve formed_ts from the FIRST impulse in the chain (C1 of FVG1 = bar 11)
    """
    df = _make_three_consecutive_bullish_fvg_df()

    # Without merging: exactly 3 individual bullish FVGs
    r_split = detect_fvg(df, join_consecutive=False, min_width_atr=0.05)
    bullish_split = [f for f in r_split["fvgs"] if f["type"] == "bullish"]
    assert len(bullish_split) == 3, (
        f"Expected 3 individual bullish FVGs (join=False), got {len(bullish_split)}"
    )

    # With merging: exactly 1 merged zone
    r_merged = detect_fvg(df, join_consecutive=True, min_width_atr=0.05)
    bullish_merged = [f for f in r_merged["fvgs"] if f["type"] == "bullish"]
    assert len(bullish_merged) == 1, (
        f"Expected 1 merged bullish FVG (join=True), got {len(bullish_merged)}"
    )

    merged = bullish_merged[0]

    # Merged boundaries cover the full span of all three individual zones
    assert merged["upper"] == max(f["upper"] for f in bullish_split), (
        f"Merged upper {merged['upper']} != max individual {max(f['upper'] for f in bullish_split)}"
    )
    assert merged["lower"] == min(f["lower"] for f in bullish_split), (
        f"Merged lower {merged['lower']} != min individual {min(f['lower'] for f in bullish_split)}"
    )

    # Merged zone is strictly wider than any single component
    max_individual_width = max(f["upper"] - f["lower"] for f in bullish_split)
    assert merged["upper"] - merged["lower"] > max_individual_width

    # Zone is still active (pullback lows stay above lower=100)
    assert merged["fill_state"] in ("untouched", "IOFED", "CE_tagged")

    # No internal field leaked into public output
    assert "_bar_idx" not in merged

    # formed_ts belongs to the first impulse candle (bar 11 = 2026-01-01T11:00:00+00:00)
    assert "T11:00:00" in merged["formed_ts"]


def test_join_consecutive_false_preserves_individuals(fvg_bullish_df):
    """
    join_consecutive=False must never merge zones — it must return at least as
    many FVGs as the merged version.  The fixture has two adjacent bullish FVGs
    (idx=19 and idx=20) so split gives 2, merged gives 1.
    """
    r_split  = detect_fvg(fvg_bullish_df, join_consecutive=False)
    r_merged = detect_fvg(fvg_bullish_df, join_consecutive=True)
    assert r_split["count_active"] >= r_merged["count_active"], (
        f"split ({r_split['count_active']}) must be >= merged ({r_merged['count_active']})"
    )
