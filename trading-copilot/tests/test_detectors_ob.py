"""
Tests for copilot/detectors/order_block.py — swing-break algorithm.

Each OB is the deepest-retracement candle (lowest low for bullish, highest high
for bearish) in the window between a confirmed structural swing and the bar whose
close finally breaks that swing level.

Fixture design principle:
  Bars are constructed so that the swing index, OB candle index, and breakout bar
  are all known in advance. The test then asserts the detector finds an OB at the
  expected price levels, letting us verify the algorithm without relying on
  accidental properties of real-market data.
"""

import pandas as pd
import pytest
from copilot.detectors.order_block import detect_order_block


# ── Fixture builders ──────────────────────────────────────────────────────────

def _make_df(rows: list[dict]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="1h", tz="UTC")
    df = pd.DataFrame(rows, index=idx)
    df.index.name = "ts"
    return df[["open", "high", "low", "close", "volume"]].astype("float64")


def _bullish_ob_df() -> pd.DataFrame:
    """
    Bullish OB scenario (swing_lookback=3).

    Timeline
    --------
    idx 0-5  : neutral bars  (high=101, low=99)
    idx 6    : swing HIGH peak  (high=120, low=110)  ← confirmed by bars 7-9
    idx 7-9  : post-peak descent (highs 115, 112, 110 — all < 120)
    idx 10-14: window between swing and breakout
               idx 11 has the LOWEST LOW = 103.0  ← expected OB candle
    idx 15   : BREAKOUT  (close=122 > 120)  ← triggers OB
    idx 16-24: FLAT at 122 (high=122.2, low=121.8)
               Flat ensures no new swing high forms above 124 and no close
               ever exceeds 124 — prevents a second OB from being triggered.

    Expected OB: bullish, high=108.0, low=103.0, midpoint=105.5
    is_mitigated: False  (flat lows 121.8 >> midpoint 105.5)
    """
    rows = []
    # idx 0-5: neutral
    for _ in range(6):
        rows.append({"open": 99.5, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 500.0})
    # idx 6: swing HIGH
    rows.append({"open": 112.0, "high": 120.0, "low": 110.0, "close": 118.0, "volume": 2000.0})
    # idx 7-9: post-peak (highs < 120, confirming swing)
    rows.append({"open": 116.0, "high": 115.0, "low": 111.0, "close": 112.0, "volume": 1200.0})
    rows.append({"open": 112.0, "high": 112.0, "low": 108.0, "close": 109.0, "volume": 1000.0})
    rows.append({"open": 109.0, "high": 110.0, "low": 106.0, "close": 107.0, "volume":  900.0})
    # idx 10: window bar
    rows.append({"open": 107.0, "high": 109.0, "low": 105.0, "close": 106.0, "volume":  800.0})
    # idx 11: DEEPEST LOW — OB candle (low=103.0, high=108.0)
    rows.append({"open": 104.0, "high": 108.0, "low": 103.0, "close": 104.0, "volume":  700.0})
    # idx 12-14: recovery (lows above midpoint 105.5)
    rows.append({"open": 105.0, "high": 110.0, "low": 106.0, "close": 108.0, "volume":  800.0})
    rows.append({"open": 108.0, "high": 112.0, "low": 108.0, "close": 110.0, "volume":  900.0})
    rows.append({"open": 110.0, "high": 115.0, "low": 110.0, "close": 113.0, "volume": 1000.0})
    # idx 15: BREAKOUT — close=122 > 120 (swing high)
    rows.append({"open": 115.0, "high": 124.0, "low": 119.0, "close": 122.0, "volume": 2500.0})
    # idx 16-24: FLAT (no new swing highs > 124, no second OB trigger)
    for _ in range(9):
        rows.append({"open": 122.0, "high": 122.2, "low": 121.8, "close": 122.0, "volume": 800.0})
    return _make_df(rows)


def _bullish_ob_mitigated_df() -> pd.DataFrame:
    """
    Same setup as _bullish_ob_df.  After the breakout (idx 15), idx 16 dips to
    low=105.0 — below midpoint 105.5 — triggering mitigation.  The remaining
    bars are flat so no secondary OB can form.
    """
    rows = []
    for _ in range(6):
        rows.append({"open": 99.5, "high": 101.0, "low": 99.0,  "close": 100.0, "volume": 500.0})
    rows.append({"open": 112.0, "high": 120.0, "low": 110.0, "close": 118.0, "volume": 2000.0})
    rows.append({"open": 116.0, "high": 115.0, "low": 111.0, "close": 112.0, "volume": 1200.0})
    rows.append({"open": 112.0, "high": 112.0, "low": 108.0, "close": 109.0, "volume": 1000.0})
    rows.append({"open": 109.0, "high": 110.0, "low": 106.0, "close": 107.0, "volume":  900.0})
    rows.append({"open": 107.0, "high": 109.0, "low": 105.0, "close": 106.0, "volume":  800.0})
    rows.append({"open": 104.0, "high": 108.0, "low": 103.0, "close": 104.0, "volume":  700.0})
    rows.append({"open": 105.0, "high": 110.0, "low": 106.0, "close": 108.0, "volume":  800.0})
    rows.append({"open": 108.0, "high": 112.0, "low": 108.0, "close": 110.0, "volume":  900.0})
    rows.append({"open": 110.0, "high": 115.0, "low": 110.0, "close": 113.0, "volume": 1000.0})
    rows.append({"open": 115.0, "high": 124.0, "low": 119.0, "close": 122.0, "volume": 2500.0})
    # idx 16: deep return — low=105.0 <= midpoint 105.5 → is_mitigated=True
    rows.append({"open": 122.0, "high": 122.5, "low": 105.0, "close": 120.0, "volume": 1500.0})
    # idx 17-24: flat at 120 (no new structural events)
    for _ in range(8):
        rows.append({"open": 120.0, "high": 120.2, "low": 119.8, "close": 120.0, "volume": 800.0})
    return _make_df(rows)


def _bearish_ob_df() -> pd.DataFrame:
    """
    Bearish OB scenario (swing_lookback=3).

    Timeline
    --------
    idx 0-5  : neutral bars  (high=201, low=199)
    idx 6    : swing LOW bottom  (high=190, low=180)  ← confirmed by bars 7-9
    idx 7-9  : post-bottom recovery (lows 185, 188, 189 — all > 180)
    idx 10-14: window between swing and breakout
               idx 11 has the HIGHEST HIGH = 197.0  ← expected OB candle
    idx 15   : BREAKOUT  (close=178 < 180)  ← triggers OB
    idx 16-24: FLAT at 178 (high=178.2, low=177.8)
               Flat ensures no new swing low forms below 177 and no close
               drops below 177 — prevents a second OB from being triggered.

    Expected OB: bearish, high=197.0, low=192.0, midpoint=194.5
    is_mitigated: False  (flat highs 178.2 << midpoint 194.5)
    """
    rows = []
    for _ in range(6):
        rows.append({"open": 200.5, "high": 201.0, "low": 199.0, "close": 200.0, "volume": 500.0})
    # idx 6: swing LOW
    rows.append({"open": 188.0, "high": 190.0, "low": 180.0, "close": 182.0, "volume": 2000.0})
    # idx 7-9: post-bottom (lows > 180, confirming swing)
    rows.append({"open": 184.0, "high": 189.0, "low": 185.0, "close": 187.0, "volume": 1200.0})
    rows.append({"open": 187.0, "high": 192.0, "low": 188.0, "close": 190.0, "volume": 1000.0})
    rows.append({"open": 190.0, "high": 194.0, "low": 189.0, "close": 191.0, "volume":  900.0})
    # idx 10: window bar
    rows.append({"open": 191.0, "high": 195.0, "low": 190.0, "close": 193.0, "volume":  800.0})
    # idx 11: HIGHEST HIGH — OB candle (high=197.0, low=192.0)
    rows.append({"open": 193.0, "high": 197.0, "low": 192.0, "close": 194.0, "volume":  700.0})
    # idx 12-14: declining (highs < 197)
    rows.append({"open": 193.0, "high": 195.0, "low": 191.0, "close": 193.0, "volume":  800.0})
    rows.append({"open": 192.0, "high": 193.0, "low": 189.0, "close": 191.0, "volume":  900.0})
    rows.append({"open": 190.0, "high": 190.0, "low": 186.0, "close": 188.0, "volume": 1000.0})
    # idx 15: BREAKOUT — close=178 < 180 (swing low)
    rows.append({"open": 184.0, "high": 184.0, "low": 177.0, "close": 178.0, "volume": 2500.0})
    # idx 16-24: FLAT (no new swing lows < 177, no second OB trigger)
    for _ in range(9):
        rows.append({"open": 178.0, "high": 178.2, "low": 177.8, "close": 178.0, "volume": 800.0})
    return _make_df(rows)


def _bearish_ob_mitigated_df() -> pd.DataFrame:
    """
    Same setup as _bearish_ob_df.  After the breakout (idx 15), idx 16 spikes to
    high=195.0 — above midpoint 194.5 — triggering mitigation.  The spike bar's
    low is kept at 178.0 (above bar 15's low=177) to avoid creating a second swing
    low that would generate a spurious secondary OB.  Remaining bars are flat.
    """
    rows = []
    for _ in range(6):
        rows.append({"open": 200.5, "high": 201.0, "low": 199.0, "close": 200.0, "volume": 500.0})
    rows.append({"open": 188.0, "high": 190.0, "low": 180.0, "close": 182.0, "volume": 2000.0})
    rows.append({"open": 184.0, "high": 189.0, "low": 185.0, "close": 187.0, "volume": 1200.0})
    rows.append({"open": 187.0, "high": 192.0, "low": 188.0, "close": 190.0, "volume": 1000.0})
    rows.append({"open": 190.0, "high": 194.0, "low": 189.0, "close": 191.0, "volume":  900.0})
    rows.append({"open": 191.0, "high": 195.0, "low": 190.0, "close": 193.0, "volume":  800.0})
    rows.append({"open": 193.0, "high": 197.0, "low": 192.0, "close": 194.0, "volume":  700.0})
    rows.append({"open": 193.0, "high": 195.0, "low": 191.0, "close": 193.0, "volume":  800.0})
    rows.append({"open": 192.0, "high": 193.0, "low": 189.0, "close": 191.0, "volume":  900.0})
    rows.append({"open": 190.0, "high": 190.0, "low": 186.0, "close": 188.0, "volume": 1000.0})
    rows.append({"open": 184.0, "high": 184.0, "low": 177.0, "close": 178.0, "volume": 2500.0})
    # idx 16: upward spike — high=195.0 >= midpoint 194.5 → is_mitigated=True
    #          low=178.0 kept above 177 to avoid creating a new swing-low trigger
    rows.append({"open": 178.0, "high": 195.0, "low": 178.0, "close": 180.0, "volume": 1500.0})
    # idx 17-24: flat at 178 (no new structural events, no close below 177)
    for _ in range(8):
        rows.append({"open": 178.0, "high": 178.2, "low": 177.8, "close": 178.0, "volume": 800.0})
    return _make_df(rows)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBullishOB:
    """Bullish OB: detected at correct candle, correct zone, correct mitigation state."""

    def test_bullish_ob_detected(self):
        """OB is found and is bullish."""
        df = _bullish_ob_df()
        result = detect_order_block(df, lookback=60, swing_lookback=3)
        assert result["count"] >= 1
        bullish = [o for o in result["obs"] if o["type"] == "bullish"]
        assert len(bullish) >= 1

    def test_bullish_ob_zone_is_correct(self):
        """
        The OB candle is the one with lowest low in the window — idx=11.
        Expected zone: high=108.0, low=103.0.
        """
        df = _bullish_ob_df()
        result = detect_order_block(df, lookback=60, swing_lookback=3)
        ob = next(o for o in result["obs"] if o["type"] == "bullish")
        # OB candle idx=11: high=108.0, low=103.0
        assert abs(ob["high"] - 108.0) < 0.5, f"Expected OB high ≈108, got {ob['high']}"
        assert abs(ob["low"]  - 103.0) < 0.5, f"Expected OB low  ≈103, got {ob['low']}"
        assert ob["high"] > ob["low"]

    def test_bullish_ob_not_mitigated(self):
        """Follow-through stays above midpoint 105.5 → OB is unmitigated."""
        df = _bullish_ob_df()
        result = detect_order_block(df, lookback=60, swing_lookback=3)
        ob = next(o for o in result["obs"] if o["type"] == "bullish")
        assert ob["is_mitigated"] is False

    def test_bullish_ob_mitigated_when_price_returns(self):
        """When follow-through dips to low=105.0 < midpoint 105.5 → is_mitigated=True."""
        df = _bullish_ob_mitigated_df()
        result = detect_order_block(df, lookback=60, swing_lookback=3)
        ob = next(o for o in result["obs"] if o["type"] == "bullish")
        assert ob["is_mitigated"] is True


class TestBearishOB:
    """Bearish OB: detected at correct candle, correct zone, correct mitigation state."""

    def test_bearish_ob_detected(self):
        df = _bearish_ob_df()
        result = detect_order_block(df, lookback=60, swing_lookback=3)
        assert result["count"] >= 1
        bearish = [o for o in result["obs"] if o["type"] == "bearish"]
        assert len(bearish) >= 1

    def test_bearish_ob_zone_is_correct(self):
        """
        OB candle is the one with highest high in the window — idx=11.
        Expected zone: high=197.0, low=192.0.
        """
        df = _bearish_ob_df()
        result = detect_order_block(df, lookback=60, swing_lookback=3)
        ob = next(o for o in result["obs"] if o["type"] == "bearish")
        assert abs(ob["high"] - 197.0) < 0.5, f"Expected OB high ≈197, got {ob['high']}"
        assert abs(ob["low"]  - 192.0) < 0.5, f"Expected OB low  ≈192, got {ob['low']}"
        assert ob["high"] > ob["low"]

    def test_bearish_ob_not_mitigated(self):
        """Follow-through stays below midpoint 194.5 → OB is unmitigated."""
        df = _bearish_ob_df()
        result = detect_order_block(df, lookback=60, swing_lookback=3)
        ob = next(o for o in result["obs"] if o["type"] == "bearish")
        assert ob["is_mitigated"] is False

    def test_bearish_ob_mitigated_when_price_returns(self):
        """When follow-through spikes to high=195.0 >= midpoint 194.5 → is_mitigated=True."""
        df = _bearish_ob_mitigated_df()
        result = detect_order_block(df, lookback=60, swing_lookback=3)
        ob = next(o for o in result["obs"] if o["type"] == "bearish")
        assert ob["is_mitigated"] is True


class TestEdgeCases:

    def test_no_ob_in_flat_market(self, flat_df):
        """
        Flat market: all prices identical → close never strictly exceeds any
        swing high (swing price == close), so no OB trigger fires.
        """
        result = detect_order_block(flat_df, swing_lookback=3)
        assert result["count"] == 0

    def test_insufficient_data(self, tiny_df):
        result = detect_order_block(tiny_df)
        assert result.get("status") == "insufficient_data"

    def test_return_schema(self):
        """All expected keys are present in every returned OB entry."""
        df = _bullish_ob_df()
        result = detect_order_block(df, swing_lookback=3)
        assert "obs" in result
        assert "count" in result
        assert isinstance(result["count"], int)
        required_keys = {"type", "high", "low", "formed_ts",
                         "has_fvg_after", "is_mitigated", "distance_atr", "age_bars"}
        for ob in result["obs"]:
            assert ob["type"] in ("bullish", "bearish")
            assert ob["high"] > ob["low"]
            assert required_keys <= ob.keys(), (
                f"Missing keys: {required_keys - ob.keys()}"
            )
            assert isinstance(ob["has_fvg_after"], bool)
            assert isinstance(ob["is_mitigated"], bool)
            assert isinstance(ob["age_bars"], int)
            assert ob["age_bars"] >= 0
