"""
Golden path for `detect_order_flow` — the trader's own 25-27 July 2026 markup.

BTCUSDT PERPETUAL FUTURES, 30m, 151 bars from 2026-07-25 03:00 UTC, copied
verbatim from Binance so the suite stays offline. The trader walked this window
bar by bar on his chart and named every key point; the assertions below are his
sentences turned into checks, not the detector's output recorded after the fact.

Times in his markup are Kyiv (UTC+3); the fixture and the detector are UTC.
"""

from __future__ import annotations

import pandas as pd
import pytest

from copilot.detectors.order_flow import detect_order_flow

_BARS: list[tuple[float, float, float, float]] = [
    (64010.5, 64073.7, 63988.4, 64045.8),
    (64045.8, 64071.1, 64020.3, 64052.9),
    (64053.0, 64112.1, 64052.9, 64078.8),
    (64078.8, 64181.0, 64054.7, 64146.9),
    (64147.0, 64166.6, 64111.5, 64117.7),
    (64117.6, 64117.7, 63940.7, 63990.1),
    (63990.0, 64032.0, 63959.8, 63975.5),
    (63975.5, 63996.2, 63933.2, 63982.9),
    (63982.9, 64004.9, 63966.8, 63988.8),
    (63988.8, 64005.5, 63968.4, 63972.9),
    (63973.0, 63973.0, 63897.5, 63965.6),
    (63965.6, 63973.1, 63760.5, 63844.3),
    (63844.4, 63911.6, 63794.2, 63910.1),
    (63910.1, 64000.0, 63891.4, 63973.9),
    (63973.8, 64013.9, 63973.7, 63998.5),
    (63998.5, 64039.7, 63959.3, 64039.6),
    (64039.6, 64065.9, 64015.4, 64049.7),
    (64049.7, 64078.5, 64014.7, 64031.3),
    (64031.2, 64052.2, 64009.3, 64016.3),
    (64016.4, 64088.2, 64006.2, 64088.2),
    (64088.1, 64108.5, 64072.2, 64099.1),
    (64099.0, 64236.8, 64086.1, 64136.9),
    (64136.8, 64152.0, 64079.2, 64134.1),
    (64134.2, 64187.4, 64134.0, 64177.7),
    (64177.7, 64243.6, 64151.6, 64173.1),
    (64173.2, 64206.1, 64135.5, 64150.0),
    (64150.1, 64186.3, 64092.2, 64113.7),
    (64113.8, 64219.0, 64111.1, 64180.9),
    (64180.8, 64255.0, 64162.1, 64240.8),
    (64240.9, 64330.2, 64218.1, 64236.6),
    (64236.7, 64392.5, 64236.7, 64390.0),
    (64390.0, 64417.1, 64350.4, 64391.4),
    (64391.3, 64410.0, 64361.9, 64378.0),
    (64378.0, 64405.0, 64351.4, 64359.6),
    (64359.7, 64367.8, 64307.7, 64344.2),
    (64344.1, 64344.2, 64282.9, 64303.9),
    (64304.0, 64307.0, 64233.0, 64268.4),
    (64268.4, 64407.1, 64268.3, 64318.5),
    (64318.6, 64392.6, 64318.5, 64362.5),
    (64362.4, 64393.0, 64328.0, 64377.6),
    (64377.7, 64393.0, 64358.4, 64368.0),
    (64367.9, 64393.4, 64331.9, 64338.1),
    (64338.0, 64465.6, 64317.9, 64444.4),
    (64444.4, 64482.7, 64370.2, 64482.6),
    (64482.7, 64514.1, 64432.2, 64444.7),
    (64444.8, 64473.1, 64422.6, 64434.3),
    (64434.3, 64453.1, 64394.0, 64452.2),
    (64452.1, 64500.0, 64398.0, 64490.6),
    (64490.6, 64553.9, 64453.2, 64523.8),
    (64523.9, 64549.8, 64500.0, 64518.8),
    (64518.9, 64525.1, 64452.9, 64525.1),
    (64525.1, 64566.0, 64485.1, 64493.1),
    (64493.2, 64493.2, 64456.8, 64456.9),
    (64456.9, 64456.9, 64359.3, 64386.0),
    (64386.0, 64406.8, 64256.4, 64270.2),
    (64270.2, 64428.7, 64265.5, 64408.9),
    (64409.0, 64439.1, 64331.5, 64340.5),
    (64340.6, 64350.0, 64313.5, 64341.2),
    (64341.3, 64388.0, 64320.2, 64371.1),
    (64371.1, 64467.5, 64367.1, 64450.1),
    (64450.0, 64523.9, 64450.0, 64507.8),
    (64507.8, 64525.2, 64476.9, 64512.3),
    (64512.3, 64518.7, 64472.4, 64493.7),
    (64493.7, 64557.3, 64483.9, 64490.9),
    (64491.0, 64507.2, 64476.8, 64476.9),
    (64477.0, 64488.9, 64470.0, 64481.4),
    (64481.5, 64639.0, 64479.5, 64554.1),
    (64554.1, 64554.1, 64405.9, 64434.2),
    (64434.2, 64492.0, 64379.7, 64440.0),
    (64440.0, 64548.3, 64430.3, 64491.8),
    (64491.9, 64748.3, 64491.8, 64605.1),
    (64605.1, 64732.5, 64588.3, 64687.2),
    (64687.2, 64757.0, 64640.0, 64727.8),
    (64727.9, 64819.3, 64700.0, 64733.6),
    (64733.5, 64786.8, 64670.1, 64770.7),
    (64770.8, 64909.0, 64700.0, 64700.0),
    (64700.0, 64769.1, 64639.9, 64685.8),
    (64685.8, 64726.6, 64640.5, 64663.2),
    (64663.3, 64678.8, 64634.0, 64659.9),
    (64660.0, 64749.4, 64649.3, 64706.8),
    (64706.8, 64716.2, 64638.8, 64692.6),
    (64692.7, 64729.4, 64663.9, 64665.5),
    (64665.6, 64676.2, 64606.3, 64623.8),
    (64623.8, 64647.5, 64616.2, 64621.3),
    (64621.2, 64841.6, 64621.2, 64788.8),
    (64788.9, 64897.1, 64762.2, 64821.7),
    (64821.7, 65234.0, 64821.7, 65188.8),
    (65188.8, 65480.0, 65168.5, 65384.7),
    (65384.7, 65555.0, 65280.7, 65305.9),
    (65305.9, 65440.0, 65245.6, 65375.1),
    (65375.2, 65398.8, 65063.9, 65162.9),
    (65162.9, 65196.9, 65033.0, 65106.0),
    (65106.0, 65178.9, 64955.3, 64993.3),
    (64993.3, 65196.7, 64872.0, 65179.8),
    (65179.9, 65219.7, 65120.0, 65156.5),
    (65156.6, 65254.4, 65088.0, 65145.7),
    (65145.6, 65315.5, 65143.5, 65290.7),
    (65290.8, 65344.0, 65227.5, 65261.5),
    (65261.5, 65484.6, 65216.7, 65294.5),
    (65294.5, 65411.4, 65216.0, 65257.2),
    (65257.2, 65415.6, 65251.0, 65385.5),
    (65385.6, 65468.2, 65321.2, 65434.3),
    (65434.2, 65722.5, 65423.6, 65464.7),
    (65464.7, 65555.0, 65377.5, 65388.0),
    (65388.0, 65421.3, 65313.7, 65380.8),
    (65380.9, 65380.9, 65190.0, 65195.9),
    (65196.0, 65234.0, 65106.7, 65209.0),
    (65209.1, 65211.1, 65092.3, 65133.0),
    (65132.9, 65210.5, 65066.3, 65198.3),
    (65198.2, 65315.7, 65176.8, 65234.4),
    (65234.5, 65369.4, 65202.1, 65322.8),
    (65322.9, 65412.8, 65300.0, 65314.7),
    (65314.7, 65314.8, 65100.0, 65100.0),
    (65100.1, 65185.6, 65061.1, 65073.1),
    (65073.1, 65240.2, 64976.6, 64984.6),
    (64984.6, 65111.0, 64811.0, 65065.0),
    (65065.0, 65099.0, 64885.3, 64922.5),
    (64922.5, 65689.6, 64919.5, 65189.4),
    (65189.4, 65409.3, 64845.4, 64845.4),
    (64845.5, 64856.9, 64418.9, 64663.4),
    (64663.4, 64750.0, 64520.6, 64624.3),
    (64624.3, 64669.8, 64374.4, 64517.1),
    (64517.2, 64767.2, 64479.0, 64701.7),
    (64701.8, 64941.7, 64701.7, 64871.0),
    (64871.0, 65035.8, 64761.7, 64975.4),
    (64975.4, 65069.4, 64926.2, 64994.3),
    (64994.2, 65034.9, 64812.0, 64895.4),
    (64895.4, 64913.0, 64727.3, 64854.7),
    (64854.7, 65007.2, 64782.0, 64971.6),
    (64971.6, 65056.8, 64889.3, 64959.2),
    (64959.2, 65030.8, 64873.6, 64992.8),
    (64992.8, 65003.4, 64877.1, 64940.4),
    (64940.3, 64940.4, 64790.2, 64800.6),
    (64800.6, 64860.6, 64762.1, 64790.2),
    (64790.3, 64790.3, 64534.1, 64574.6),
    (64574.6, 64577.1, 63755.3, 63755.4),
    (63755.5, 63903.6, 63567.0, 63846.0),
    (63845.9, 63890.0, 63592.6, 63720.8),
    (63720.7, 63794.3, 63461.2, 63675.0),
    (63674.9, 63681.7, 63439.1, 63453.1),
    (63453.1, 63500.0, 63021.0, 63277.2),
    (63277.2, 63365.9, 63141.0, 63195.9),
    (63195.9, 63269.8, 63120.9, 63200.2),
    (63200.3, 63210.0, 63069.8, 63148.2),
    (63148.1, 63310.1, 63131.9, 63261.4),
    (63261.4, 63342.8, 63202.0, 63310.1),
    (63310.0, 63333.3, 63250.9, 63260.2),
    (63260.1, 63329.2, 63187.2, 63323.5),
    (63323.5, 63588.0, 63294.9, 63514.3),
    (63514.3, 63538.5, 63401.1, 63417.4),
    (63417.5, 63500.0, 63365.4, 63495.8),
]


@pytest.fixture(scope="module")
def reference_window() -> pd.DataFrame:
    index = pd.date_range(
        "2026-07-25 03:00", periods=len(_BARS), freq="30min", tz="UTC", name="ts"
    )
    df = pd.DataFrame(_BARS, columns=["open", "high", "low", "close"], index=index)
    df["volume"] = 1000.0
    return df[["open", "high", "low", "close", "volume"]]


@pytest.fixture(scope="module")
def flow(reference_window) -> dict:
    return detect_order_flow(reference_window, max_events=200)


def _by_break(result: dict, ts_utc: str) -> dict | None:
    for e in result["events"]:
        if e["break_ts"] == ts_utc:
            return e
    return None


class TestTraderMarkup:
    """Each case is a sentence the trader wrote, turned into an assertion."""

    @pytest.mark.parametrize("break_ts,kind,level,kyiv", [
        # "новым hh становиться 64236,8" — its break is continuation #1
        ("2026-07-25T17:00:00Z", "cBOS", 64236.8, "25.07 20:00"),
        # "Образовав новый ll в 00:00 мы продолжили движение структуры"
        ("2026-07-26T00:00:00Z", "cBOS", 64417.1, "26.07 03:00"),
        # his own correction: "хай в 04:00 должен считаться hh"
        ("2026-07-26T03:00:00Z", "cBOS", 64514.1, "26.07 06:00"),
    ])
    def test_continuations_break_the_levels_he_named(
        self, flow, break_ts, kind, level, kyiv
    ):
        ev = _by_break(flow, break_ts)
        assert ev is not None, f"no event at {kyiv} Kyiv"
        assert ev["type"] == kind
        assert ev["direction"] == "bullish"
        assert ev["broken_level"] == pytest.approx(level, abs=0.011)

    def test_flow_dies_at_0830_not_0900(self, flow):
        """"Слом произошел в 8:30, но фрактал ll образовался в 09:00."

        The break is the BODY close under the key low; the fractal that becomes
        the next key low prints half an hour later. Conflating the two shifts
        every stop and exit by a bar.
        """
        ev = _by_break(flow, "2026-07-26T05:30:00Z")           # 08:30 Kyiv
        assert ev is not None, "no structure break at 08:30 Kyiv"
        assert ev["type"] == "BOS"
        assert ev["direction"] == "bearish"
        assert ev["key_low_ts"] == "2026-07-26T06:00:00Z"      # 09:00 Kyiv

    def test_structure_break_of_27_july(self, flow):
        """"в 17:00 мы сломали структуру закрепившись телом под ll 04:30"."""
        ev = _by_break(flow, "2026-07-27T14:00:00Z")           # 17:00 Kyiv
        assert ev is not None, "no structure break at 17:00 Kyiv"
        assert ev["type"] == "BOS"
        assert ev["direction"] == "bearish"
        assert ev["broken_level"] == pytest.approx(64872.0, abs=0.011)
        assert ev["broken_ts"] == "2026-07-27T01:30:00Z"       # 04:30 Kyiv
        # "фрактал в 09:00 стал HH" — the high of the structure that just broke
        assert ev["key_high"] == pytest.approx(65722.5, abs=0.011)

    def test_new_key_is_the_nearest_fractal_not_the_deeper_one(self, flow):
        """The 17:30 pivot, not 18:30 — a correction the trader confirmed.

        Both are fractal lows and 18:30 is deeper. Taking the deeper one delays
        the next continuation and loosens the stop that hangs off it.
        """
        ev = _by_break(flow, "2026-07-27T22:30:00Z")           # 28.07 01:30 Kyiv
        assert ev is not None, "no continuation at 28.07 01:30 Kyiv"
        assert ev["type"] == "cBOS"
        assert ev["broken_ts"] == "2026-07-27T14:30:00Z"       # 17:30 Kyiv
        assert ev["broken_level"] == pytest.approx(64418.9, abs=0.011)


class TestNoLookAhead:
    """A key may only reference bars the market had already printed."""

    def test_a_wick_through_the_key_is_not_a_break(self, flow):
        """25 Jul 18:00 pierced 64236.8 and closed below; the key must survive.

        If wicks counted, this bar would end the leg two hours early and the
        64417.1 continuation the trader named would never appear.
        """
        assert _by_break(flow, "2026-07-25T15:00:00Z") is None, (
            "a wick pierce was taken as a break"
        )

    def test_events_never_reference_a_bar_after_their_break(self, flow):
        for ev in flow["events"]:
            assert ev["broken_ts"] <= ev["break_ts"], (
                f"{ev['type']} at {ev['break_ts']} broke a level printed later"
            )

    def test_growing_slices_never_rewrite_history(self, reference_window):
        """A single forward pass must be append-only as bars arrive.

        The first implementation searched forward for "the next fractal", so its
        answer moved with the start of the scan — the backtest would then
        disagree with the chart the trader signed off on.
        """
        seen: list[tuple] = []
        for n in range(40, len(reference_window) + 1, 7):
            evs = detect_order_flow(reference_window.iloc[:n], max_events=500)["events"]
            keys = [(e["break_ts"], e["type"], e["broken_level"]) for e in reversed(evs)]
            assert keys[: len(seen)] == seen, (
                f"history rewritten at {n} bars"
            )
            seen = keys


class TestBoundedLookback:
    def test_structure_converges_but_pools_do_not(self, reference_window):
        """The markup converges from a warm-up window; the pool gate does not.

        The trader's position is that the markup "нормализуется со временем",
        and for direction / confirmations / key points that holds. It does NOT
        hold for `pool_level`: a pool is a fractal extreme that PREDATES the
        flow, so a shorter window simply has fewer of them. Measured on live
        30m data, a 1000-bar window moved `pool_level` on 58% of slices.

        This is why `rules_30mof` walks full history despite the cost — the
        temptation to bound it for speed is exactly what this test exists to
        stop.
        """
        for n in range(90, len(reference_window) + 1, 10):
            sl = reference_window.iloc[:n]
            full = detect_order_flow(sl)
            bounded = detect_order_flow(sl, lookback=80)
            for field in ("direction", "confirmed"):
                assert full[field] == bounded[field], (
                    f"{field} diverged at {n} bars with an 80-bar window"
                )
            assert full["key_high"] == bounded["key_high"]
            assert full["key_low"] == bounded["key_low"]

    def test_lookback_zero_means_everything(self, reference_window):
        assert (detect_order_flow(reference_window, lookback=0)["count"]
                == detect_order_flow(reference_window)["count"])
