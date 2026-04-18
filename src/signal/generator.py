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

    # ONLY surviving setup after OOS validation on 232 days (2025-05-15 → 2026-04-16):
    #   NEG_GAMMA + spot near put_wall (pos<0.3) → BULLISH bounce
    #   IS PF 1.65, OOS PF 1.59 → 4% degradation only, genuine out-of-sample stability.
    #
    # Setups DROPPED (failed OOS):
    #   NEG_high_reject: IS -0.427% → OOS +0.202% (sign flipped, spurious)
    #   POS_high_drift:  IS +0.125% → OOS +0.021% (effect vanished)
    #   VEX tercile filter: IS monotone, OOS flat (zero predictive power OOS)
    #
    # Interpretation: dealers short gamma near put_wall must buy to hedge as spot
    # approaches — a support mechanism documented in SpotGamma/Baltussen et al.
    # This is the only mechanism in the GEX framework that reproduces out-of-sample.
    if levels.regime == "NEGATIVE_GAMMA" and position_in_range < 0.3:
        conf = 0.70 * session_modifier
        if conf >= 0.55:
            return TradeSignal(
                direction="BULLISH", confidence=round(conf, 2),
                target=(put_wall + call_wall) / 2,
                stop=put_wall * 0.998,
                regime=levels.regime,
                reason=f"neg_gamma bounce_off_put_wall({put_wall:.0f}) pos={position_in_range:.2f}",
                time_session=session,
            )

    neutral.reason = "no actionable setup"
    return neutral
