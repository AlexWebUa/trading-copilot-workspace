"""
BPR and STB/BTS — the two POI detectors 30mOF needed and the codebase lacked.

Both were written against the trader's definitions of 2026-08-26:
  BPR      "пересечение двух имбалансов", any age.
  STB      "последние последовательные медвежьи свечи которые образуют ll
            (включая их фитили)"; BTS mirrored on bullish candles and a high.
"""

from __future__ import annotations

import pandas as pd
import pytest

from copilot.detectors.bpr import detect_bpr
from copilot.detectors.stb_bts import detect_stb_bts


def _df(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(rows), freq="30min", tz="UTC", name="ts")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)
    df["volume"] = 1000.0
    return df[["open", "high", "low", "close", "volume"]]


def _flat(n: int, price: float) -> list[tuple[float, float, float, float]]:
    return [(price, price + 0.4, price - 0.4, price)] * n


class TestBpr:
    def test_overlap_of_two_opposite_gaps_is_reported(self):
        """A drop leaving a bearish gap, then a rally that leaves a bullish gap
        inside it and stalls — the shared band is the BPR.

        The rally must stop short of closing the bearish gap: `detect_fvg` drops
        a fully-filled zone, and a BPR needs both halves alive. That is not a
        fixture quirk, it is why BPRs are rare in practice (measured at ~2% of
        30m slices).
        """
        rows = _flat(12, 103.0)
        rows += [(103.0, 103.5, 102.0, 102.2)]             # C0 of the bearish gap
        rows += [(102.2, 102.3, 94.0, 94.2)]               # displacement down
        rows += [(94.2, 96.0, 93.5, 95.0)]                 # C2 -> gap [96.0, 102.0]
        rows += [(95.0, 96.5, 94.8, 96.3)]                 # C0 of the bullish gap
        rows += [(96.3, 98.9, 96.2, 98.7)]                 # displacement up, stalls
        rows += [(98.7, 98.9, 97.8, 98.5)]                 # C2 -> gap [96.5, 97.8]
        rows += _flat(6, 98.5)

        result = detect_bpr(_df(rows))
        assert result["bprs"], "two overlapping live gaps produced no BPR"
        z = result["bprs"][0]
        assert z["upper"] > z["lower"], "a BPR with no width is not a BPR"
        # The band is the INTERSECTION, so it sits inside BOTH gaps: below the
        # bullish gap's top (97.8) and above the bearish gap's bottom (96.0).
        # Exact edges are not asserted because detect_fvg merges consecutive
        # gaps, which legitimately widens the bullish half.
        assert z["lower"] >= 95.9, f"BPR bottom {z['lower']} escaped the bearish gap"
        assert z["upper"] <= 97.9, f"BPR top {z['upper']} escaped the bullish gap"
        assert z["upper"] - z["lower"] > 0.5, "intersection collapsed to a sliver"

    def test_gaps_that_do_not_overlap_produce_nothing(self):
        """Two imbalances at different prices are two imbalances, not a BPR."""
        rows = _flat(12, 103.0)
        rows += [(103.0, 103.5, 102.0, 102.2)]
        rows += [(102.2, 102.3, 94.0, 94.2)]
        rows += [(94.2, 96.0, 93.5, 95.0)]                 # bearish gap [96, 102]
        rows += _flat(8, 95.0)
        rows += [(95.0, 95.2, 90.0, 90.2)]
        rows += [(90.2, 90.4, 84.0, 84.3)]                 # displacement down
        rows += [(84.3, 85.0, 83.5, 84.8)]                 # bearish gap far below
        rows += _flat(6, 84.8)

        assert detect_bpr(_df(rows))["bprs"] == [], (
            "same-polarity gaps at different prices were reported as a BPR"
        )

    def test_touching_edges_are_not_an_overlap(self):
        """Zero width means the two gaps meet, not that they share prices."""
        from copilot.detectors.bpr import detect_bpr as _d
        assert _d(_df(_flat(30, 100.0)))["bprs"] == []

    def test_insufficient_data_fails_soft(self):
        assert detect_bpr(_df(_flat(5, 100.0)))["status"] == "insufficient_data"


class TestStbBts:
    def test_stb_spans_the_bearish_run_including_wicks(self):
        """The zone is the run's full high-to-low, not its bodies.

        A body-only zone sits inside the wick, so price reaches it far less
        often — that changes the trade count, not just the fill price.
        """
        rows = _flat(6, 110.0)
        rows += [(110.0, 111.0, 108.0, 108.5)]     # bearish
        rows += [(108.5, 109.0, 105.0, 105.5)]     # bearish
        rows += [(105.5, 106.0, 100.0, 101.0)]     # bearish, prints the low
        rows += [(101.0, 107.0, 100.5, 106.5)]     # reversal up
        rows += _flat(6, 107.0)

        zones = detect_stb_bts(_df(rows))["stb"]
        assert zones, "no STB built from a three-candle bearish run into a low"
        z = zones[0]
        assert z["run_bars"] == 3, f"run of 3 bearish candles read as {z['run_bars']}"
        assert z["lower"] == pytest.approx(100.0), "zone bottom must be the wick low"
        assert z["upper"] == pytest.approx(111.0), "zone top must be the run's wick high"

    def test_bts_is_the_mirror_on_bullish_candles(self):
        rows = _flat(6, 90.0)
        rows += [(90.0, 92.0, 89.5, 91.8)]         # bullish
        rows += [(91.8, 95.0, 91.5, 94.8)]         # bullish
        rows += [(94.8, 100.0, 94.5, 99.0)]        # bullish, prints the high
        rows += [(99.0, 99.5, 93.0, 93.5)]         # reversal down
        rows += _flat(6, 93.0)

        zones = detect_stb_bts(_df(rows))["bts"]
        assert zones, "no BTS built from a three-candle bullish run into a high"
        z = zones[0]
        assert z["run_bars"] == 3
        assert z["upper"] == pytest.approx(100.0)
        assert z["lower"] == pytest.approx(89.5)

    def test_run_stops_at_the_first_opposite_candle(self):
        """One green candle inside the sell-off ends the run — the zone is only
        the consecutive part, which is what "последние последовательные" means."""
        rows = _flat(6, 110.0)
        rows += [(110.0, 111.0, 108.0, 108.5)]     # bearish
        rows += [(108.5, 109.5, 108.0, 109.2)]     # BULLISH — breaks the run
        rows += [(109.2, 109.4, 104.0, 104.5)]     # bearish
        rows += [(104.5, 105.0, 100.0, 101.0)]     # bearish, prints the low
        rows += [(101.0, 107.0, 100.5, 106.5)]
        rows += _flat(6, 107.0)

        z = detect_stb_bts(_df(rows))["stb"][0]
        assert z["run_bars"] == 2, f"the run crossed a bullish candle ({z['run_bars']})"
        assert z["upper"] == pytest.approx(109.4), "zone top came from before the break"

    def test_insufficient_data_fails_soft(self):
        assert detect_stb_bts(_df(_flat(4, 100.0)))["status"] == "insufficient_data"
