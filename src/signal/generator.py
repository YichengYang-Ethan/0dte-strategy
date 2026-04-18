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

    # Only surviving setup after 574-day 3-tier validation (2024-01 → 2026-04):
    #   NEG_GAMMA + spot very close to put_wall (pos<0.15) → BULLISH bounce
    #
    # Validation summary (1 contract, swing_1dte mode):
    #                        N    WR     PF    Sharpe
    #   ORIG_IS  (114 d)     30   60.0%  1.77  3.18    — design sample
    #   ORIG_OOS (118 d)     17   41.2%  1.77  3.56    — 1st OOS, 2025-05→2025-10
    #   EXT_OOS  (345 d)     87   54.0%  1.23  0.92    — 2nd OOS, 2024-01→2025-05
    #   ALL      (574 d)    134   53.7%  1.40  1.59
    #
    # Mechanism: in NEG_GAMMA, dealers are short gamma. Spot pinned near put_wall
    # forces dealers to buy as spot dips (delta hedging). The bounce is convex:
    # top 5 winners contribute >100% of total P&L; many small losses, few fat tails.
    #
    # Threshold evolution: pos<0.3 was the initial cut from 113-day IS. Tightening
    # to pos<0.15 after seeing EXT_OOS improved PF uniformly (IS 1.65→1.77,
    # OOS 1.59→1.77, EXT_OOS 1.08→1.23) — consistent across all 3 buckets.
    #
    # Setups DROPPED (failed OOS):
    #   NEG_high_reject: IS -0.427% → OOS +0.202% (sign flipped)
    #   POS_high_drift:  IS +0.125% → OOS +0.021% (vanished)
    #   VEX tercile filter: IS PF 1.75-4.47 → OOS PF 0.86-1.03
    #   weekend_gap_only: ORIG-OOS PF 8.72 → EXT_OOS PF 0.84 (13-trade overfit)
    #   5-day correction filter: counterproductive — fat-tail winners cluster in
    #     correction periods (skipping corrections also skips the bounces)
    if levels.regime == "NEGATIVE_GAMMA" and position_in_range < 0.15:
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
