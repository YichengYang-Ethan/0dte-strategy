"""Trade signal generation from GEX + Vanna + time-of-day."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    time_session: str  # "OPENING", "CORE", "GAMMA_RAMP", "CLOSE"


def classify_session(now: Optional[datetime] = None) -> str:
    """
    Classify current time into intraday sessions.

    GEX dynamics differ dramatically through the day:
    - OPENING (9:30-10:00): Vol spike, walls unstable. Do not trade.
    - CORE (10:00-14:00): Walls stabilize. Best signal window.
    - GAMMA_RAMP (14:00-15:30): 0DTE gamma increases exponentially.
      Walls can break. Signals need higher confidence.
    - CLOSE (15:30-16:00): Extreme gamma. Only manage, don't open.
    """
    if now is None:
        now = datetime.now()

    h, m = now.hour, now.minute
    minutes = h * 60 + m

    if minutes < 600:   # before 10:00
        return "OPENING"
    if minutes < 840:   # 10:00 - 14:00
        return "CORE"
    if minutes < 930:   # 14:00 - 15:30
        return "GAMMA_RAMP"
    return "CLOSE"


def generate_signal(
    levels: GEXLevels,
    vanna: VannaExposure,
    now: Optional[datetime] = None,
) -> TradeSignal:
    """
    Generate trade signal from GEX levels + Vanna + time-of-day.

    Rules:
    - OPENING session: never trade (walls unstable)
    - CLOSE session: never open new (only manage existing)
    - NEGATIVE_GAMMA: trending market, directional trades
    - POSITIVE_GAMMA: pinning market, mean-reversion
    - GAMMA_RAMP: require higher confidence (gamma is exponential)
    - Vanna confirms or weakens direction
    """
    session = classify_session(now)
    spot = levels.spot
    call_wall = levels.call_wall
    put_wall = levels.put_wall

    neutral = TradeSignal(
        direction="NEUTRAL", confidence=0.0,
        target=None, stop=None,
        regime=levels.regime, reason="", time_session=session,
    )

    if session == "OPENING":
        neutral.reason = "opening session — walls unstable"
        return neutral

    if session == "CLOSE":
        neutral.reason = "close session — manage only, no new trades"
        return neutral

    if call_wall is None or put_wall is None or call_wall <= put_wall:
        neutral.reason = "insufficient GEX data"
        return neutral

    range_total = call_wall - put_wall
    if range_total <= 0:
        neutral.reason = "invalid wall range"
        return neutral

    position_in_range = (spot - put_wall) / range_total

    # Confidence modifier based on session
    session_modifier = 1.0
    if session == "GAMMA_RAMP":
        session_modifier = 0.85  # require stronger signals during gamma ramp

    # Vanna alignment scoring
    def vanna_score(direction: str) -> float:
        if direction == "BULLISH":
            if vanna.direction == "BULLISH_VANNA":
                return 0.10
            if vanna.direction == "BEARISH_VANNA":
                return -0.10
        elif direction == "BEARISH":
            if vanna.direction == "BEARISH_VANNA":
                return 0.10
            if vanna.direction == "BULLISH_VANNA":
                return -0.10
        return 0.0

    if levels.regime == "NEGATIVE_GAMMA":
        # Trending market — directional trades

        if position_in_range < 0.3:
            base_conf = 0.70
            adj = base_conf + vanna_score("BEARISH")
            conf = adj * session_modifier
            if conf >= 0.55:
                return TradeSignal(
                    direction="BEARISH", confidence=round(conf, 2),
                    target=put_wall,
                    stop=spot + (spot - put_wall) * 0.3,
                    regime=levels.regime,
                    reason=f"neg_gamma near put_wall({put_wall:.0f}) pos={position_in_range:.2f}",
                    time_session=session,
                )

        if position_in_range > 0.7:
            base_conf = 0.70
            adj = base_conf + vanna_score("BULLISH")
            conf = adj * session_modifier
            if conf >= 0.55:
                return TradeSignal(
                    direction="BULLISH", confidence=round(conf, 2),
                    target=call_wall,
                    stop=spot - (call_wall - spot) * 0.3,
                    regime=levels.regime,
                    reason=f"neg_gamma near call_wall({call_wall:.0f}) pos={position_in_range:.2f}",
                    time_session=session,
                )

        # Mid-range with strong vanna
        if position_in_range > 0.5 and vanna.direction == "BULLISH_VANNA":
            conf = 0.60 * session_modifier
            if conf >= 0.55:
                return TradeSignal(
                    direction="BULLISH", confidence=round(conf, 2),
                    target=call_wall,
                    stop=spot - range_total * 0.15,
                    regime=levels.regime,
                    reason=f"neg_gamma above_mid + bullish_vanna pos={position_in_range:.2f}",
                    time_session=session,
                )

        if position_in_range < 0.5 and vanna.direction == "BEARISH_VANNA":
            conf = 0.60 * session_modifier
            if conf >= 0.55:
                return TradeSignal(
                    direction="BEARISH", confidence=round(conf, 2),
                    target=put_wall,
                    stop=spot + range_total * 0.15,
                    regime=levels.regime,
                    reason=f"neg_gamma below_mid + bearish_vanna pos={position_in_range:.2f}",
                    time_session=session,
                )

    elif levels.regime == "POSITIVE_GAMMA":
        # Pinning market — mean reversion
        mid = (call_wall + put_wall) / 2

        if position_in_range > 0.80:
            conf = 0.60 * session_modifier
            if conf >= 0.55:
                return TradeSignal(
                    direction="BEARISH", confidence=round(conf, 2),
                    target=mid, stop=call_wall * 1.002,
                    regime=levels.regime,
                    reason=f"pos_gamma stretched_to_call_wall revert_to_mid({mid:.0f})",
                    time_session=session,
                )

        if position_in_range < 0.20:
            conf = 0.60 * session_modifier
            if conf >= 0.55:
                return TradeSignal(
                    direction="BULLISH", confidence=round(conf, 2),
                    target=mid, stop=put_wall * 0.998,
                    regime=levels.regime,
                    reason=f"pos_gamma stretched_to_put_wall revert_to_mid({mid:.0f})",
                    time_session=session,
                )

    neutral.reason = "no actionable setup"
    return neutral
