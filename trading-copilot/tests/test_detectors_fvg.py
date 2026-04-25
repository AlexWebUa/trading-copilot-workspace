"""Tests for copilot/detectors/fvg.py"""

from copilot.detectors.fvg import detect_fvg


def test_bullish_fvg_detected(fvg_bullish_df):
    result = detect_fvg(fvg_bullish_df)
    assert result["count_active"] >= 1
    fvg = next(f for f in result["fvgs"] if f["type"] == "bullish")
    assert fvg["upper"] > fvg["lower"]
    assert fvg["fill_state"] in ("untouched", "IOFED", "CE_tagged")
    # Zone: C0.high=102 → C2.low=105, so upper=105, lower=102
    assert 100.0 < fvg["lower"] < fvg["upper"] < 110.0


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
