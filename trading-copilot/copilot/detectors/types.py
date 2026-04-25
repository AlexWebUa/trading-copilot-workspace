"""Shared TypedDicts for detector return shapes.

All detectors return plain dicts (JSON-serializable).
TypedDicts here are for IDE autocomplete and documentation only.
"""

from typing import Literal, TypedDict


class SwingPoint(TypedDict):
    price: float
    ts: str
    strength: Literal["strong", "weak"]


class MarketStructureResult(TypedDict):
    state: Literal["bullish", "bearish", "ranging"]
    last_swing_high: SwingPoint
    last_swing_low: SwingPoint
    bars_in_state: int


class BOSResult(TypedDict):
    type: Literal["BOS", "MSS", "cBOS", "none"]
    direction: Literal["bullish", "bearish", "none"]
    broken_level: float | None
    break_ts: str | None
    displacement_candles: int
    displacement_atr_multiple: float


class FVGEntry(TypedDict):
    type: Literal["bullish", "bearish"]
    upper: float
    lower: float
    formed_ts: str
    fill_percentage: float
    fill_state: Literal["untouched", "IOFED", "CE_tagged", "filled"]
    age_bars: int


class FVGResult(TypedDict):
    fvgs: list[FVGEntry]
    count_active: int


class OBEntry(TypedDict):
    type: Literal["bullish", "bearish"]
    high: float
    low: float
    formed_ts: str
    has_fvg_after: bool
    is_mitigated: bool
    distance_atr: float


class OBResult(TypedDict):
    obs: list[OBEntry]
    count: int


class LiquidityPool(TypedDict):
    price: float
    type: Literal["EQH", "EQL", "swing_high", "swing_low"]
    touches: int
    last_touch_ts: str
    age_bars: int


class LiquiditySweep(TypedDict):
    side: Literal["buyside", "sellside"]
    swept_level: float
    sweep_ts: str
    closed_back: bool


class LiquidityResult(TypedDict):
    buyside_liquidity: list[LiquidityPool]
    sellside_liquidity: list[LiquidityPool]
    recent_sweeps: list[LiquiditySweep]


class FibZonesResult(TypedDict):
    equilibrium: float
    premium_zone: dict
    discount_zone: dict
    ote: dict
    current_price_location: Literal["premium", "discount", "equilibrium"]


class MultiTFAlignmentResult(TypedDict):
    aligned: bool
    htf_bias: Literal["bullish", "bearish", "ranging"]
    ltf_role: Literal["pullback", "continuation", "counter_trend", "unclear"]
    sync_quality: Literal["strong", "weak", "desync"]
