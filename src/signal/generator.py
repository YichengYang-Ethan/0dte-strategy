"""Trade signal generation from GEX + Vanna analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.gex.calculator import GEXLevels, VannaExposure


@dataclass
class TradeSignal:
    direction: str  # "BULLISH", "BEARISH", "NEUTRAL"
    confidence: float  # 0.0 - 1.0
    target: Optional[float]
    stop: Optional[float]
    regime: str
    reason: str


def generate_signal(
    levels: GEXLevels,
    vanna: VannaExposure,
) -> TradeSignal:
    """
    Generate trade signal from GEX levels + Vanna exposure.

    Logic:
    - NEGATIVE_GAMMA regime → trending market, directional trades work
    - POSITIVE_GAMMA regime → pinning market, mean-reversion works
    - Vanna confirms or contradicts direction
    """
    spot = levels.spot
    call_wall = levels.call_wall
    put_wall = levels.put_wall

    if call_wall is None or put_wall is None or call_wall <= put_wall:
        return TradeSignal(
            direction="NEUTRAL", confidence=0.0,
            target=None, stop=None,
            regime=levels.regime, reason="insufficient GEX data",
        )

    range_total = call_wall - put_wall
    position_in_range = (spot - put_wall) / range_total

    if levels.regime == "NEGATIVE_GAMMA":
        # Trending market — trade directionally
        if position_in_range < 0.3 and vanna.direction in ("BEARISH_VANNA", "NEUTRAL"):
            return TradeSignal(
                direction="BEARISH",
                confidence=0.70,
                target=put_wall,
                stop=spot + (spot - put_wall) * 0.3,
                regime=levels.regime,
                reason=f"neg gamma + near put wall ({put_wall:.0f}) + bearish vanna",
            )
        if position_in_range > 0.7 and vanna.direction in ("BULLISH_VANNA", "NEUTRAL"):
            return TradeSignal(
                direction="BULLISH",
                confidence=0.70,
                target=call_wall,
                stop=spot - (call_wall - spot) * 0.3,
                regime=levels.regime,
                reason=f"neg gamma + near call wall ({call_wall:.0f}) + bullish vanna",
            )
        # Mid-range in negative gamma: strong trend signal
        if position_in_range > 0.5 and vanna.direction == "BULLISH_VANNA":
            return TradeSignal(
                direction="BULLISH",
                confidence=0.60,
                target=call_wall,
                stop=spot - range_total * 0.15,
                regime=levels.regime,
                reason="neg gamma + above midpoint + bullish vanna",
            )
        if position_in_range < 0.5 and vanna.direction == "BEARISH_VANNA":
            return TradeSignal(
                direction="BEARISH",
                confidence=0.60,
                target=put_wall,
                stop=spot + range_total * 0.15,
                regime=levels.regime,
                reason="neg gamma + below midpoint + bearish vanna",
            )

    elif levels.regime == "POSITIVE_GAMMA":
        # Pinning market — mean reversion
        mid = (call_wall + put_wall) / 2
        if position_in_range > 0.80:
            return TradeSignal(
                direction="BEARISH",
                confidence=0.60,
                target=mid,
                stop=call_wall * 1.002,
                regime=levels.regime,
                reason=f"pos gamma + stretched to call wall, revert to mid ({mid:.0f})",
            )
        if position_in_range < 0.20:
            return TradeSignal(
                direction="BULLISH",
                confidence=0.60,
                target=mid,
                stop=put_wall * 0.998,
                regime=levels.regime,
                reason=f"pos gamma + stretched to put wall, revert to mid ({mid:.0f})",
            )

    return TradeSignal(
        direction="NEUTRAL", confidence=0.0,
        target=None, stop=None,
        regime=levels.regime, reason="no actionable setup",
    )
