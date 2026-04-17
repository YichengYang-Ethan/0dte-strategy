"""Realistic fill simulation for 0DTE options backtesting.

Models bid-ask spread, time-of-day spread widening, slippage,
partial fills, and adverse selection.

Key findings from research:
- Real fill ≈ mid + 30-40% of half-spread (NOT mid)
- Spreads widen ~30% in first 30 min and last hour
- IOC fills are cleaner than GTC (less adverse selection)
- 0DTE ATM spreads: SPY ~$0.02-0.05, SPX ~$0.50-1.00

Reference: r/options 1.5M-quote SPX analysis, TastyTrade fill research
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class FillResult:
    fill_price: float
    slippage: float  # cost vs mid
    spread_at_fill: float
    filled: bool
    partial_fill_pct: float  # 1.0 = full fill
    reason: str  # "FILLED", "SPREAD_TOO_WIDE", "NO_LIQUIDITY"


class FillSimulator:
    """
    Simulate realistic option fills for backtesting.

    Conservative by default — better to underestimate backtested returns
    than to overestimate them.
    """

    def __init__(
        self,
        spread_cross_pct: float = 0.35,  # pay 35% of half-spread to cross
        max_spread_pct: float = 0.30,     # reject if spread > 30% of mid
        adverse_selection_bps: float = 5,  # 5 bps adverse selection on entry
    ):
        self.spread_cross_pct = spread_cross_pct
        self.max_spread_pct = max_spread_pct
        self.adverse_selection_bps = adverse_selection_bps

    def time_of_day_spread_multiplier(self, now: Optional[datetime] = None) -> float:
        """
        Spread widens at open and close.
        10:00-14:00 = tightest (1.0x)
        9:30-10:00 = 1.3x wider
        14:00-15:30 = 1.15x wider
        15:30-16:00 = 1.5x wider (0DTE gamma explosion)
        """
        if now is None:
            now = datetime.now()

        h, m = now.hour, now.minute
        minutes = h * 60 + m

        if minutes < 600:       # 9:30-10:00
            return 1.30
        elif minutes < 840:     # 10:00-14:00
            return 1.00
        elif minutes < 930:     # 14:00-15:30
            return 1.15
        else:                   # 15:30-16:00
            return 1.50

    def estimate_spread(
        self,
        bid: float,
        ask: float,
        now: Optional[datetime] = None,
    ) -> float:
        """Estimate effective spread with time-of-day adjustment."""
        raw_spread = ask - bid
        multiplier = self.time_of_day_spread_multiplier(now)
        return raw_spread * multiplier

    def simulate_entry(
        self,
        bid: float,
        ask: float,
        direction: str = "BUY",
        now: Optional[datetime] = None,
    ) -> FillResult:
        """
        Simulate a BUY entry fill.

        Fill price = mid + spread_cross_pct × half_spread + adverse_selection
        """
        if bid <= 0 or ask <= 0 or ask <= bid:
            return FillResult(
                fill_price=0, slippage=0, spread_at_fill=0,
                filled=False, partial_fill_pct=0, reason="NO_LIQUIDITY",
            )

        mid = (bid + ask) / 2
        effective_spread = self.estimate_spread(bid, ask, now)

        if mid > 0 and effective_spread / mid > self.max_spread_pct:
            return FillResult(
                fill_price=0, slippage=0, spread_at_fill=effective_spread,
                filled=False, partial_fill_pct=0, reason="SPREAD_TOO_WIDE",
            )

        half_spread = effective_spread / 2
        crossing_cost = half_spread * self.spread_cross_pct
        adverse = mid * self.adverse_selection_bps / 10000

        if direction == "BUY":
            fill_price = mid + crossing_cost + adverse
        else:
            fill_price = mid - crossing_cost - adverse

        fill_price = round(max(fill_price, 0.01), 2)
        slippage = abs(fill_price - mid)

        return FillResult(
            fill_price=fill_price,
            slippage=slippage,
            spread_at_fill=effective_spread,
            filled=True,
            partial_fill_pct=1.0,
            reason="FILLED",
        )

    def simulate_exit(
        self,
        bid: float,
        ask: float,
        now: Optional[datetime] = None,
    ) -> FillResult:
        """
        Simulate a SELL exit fill.

        Exit fills at bid side: fill = bid + small improvement.
        Worse than entry because urgency is higher on exits.
        """
        if bid <= 0:
            # Worthless expiry
            return FillResult(
                fill_price=0.01, slippage=0, spread_at_fill=0,
                filled=True, partial_fill_pct=1.0, reason="WORTHLESS_EXPIRY",
            )

        mid = (bid + ask) / 2 if ask > bid else bid
        effective_spread = self.estimate_spread(bid, ask, now)

        # Exit at bid + 10% of spread (small improvement, conservative)
        fill_price = bid + effective_spread * 0.10
        fill_price = round(max(fill_price, 0.01), 2)
        slippage = mid - fill_price

        return FillResult(
            fill_price=fill_price,
            slippage=max(slippage, 0),
            spread_at_fill=effective_spread,
            filled=True,
            partial_fill_pct=1.0,
            reason="FILLED",
        )


def intraday_theta_decay(daily_theta: float, minutes_to_expiry: int) -> float:
    """
    Non-linear intraday theta decay for 0DTE.

    Standard BSM theta assumes linear daily decay. Reality for 0DTE:
    theta accelerates as 1/sqrt(T).

    theta_t = daily_theta × (1 / sqrt(T_remaining_fraction))

    At 3:30 PM (30 min left, T=0.077): ~3.6x daily rate
    At 3:50 PM (10 min left, T=0.026): ~6.2x daily rate
    At 3:55 PM (5 min left, T=0.013): ~8.8x daily rate

    Reference: tastylive research on intraday theta, Option Alpha studies
    """
    if minutes_to_expiry <= 0:
        return 0.0

    total_minutes = 390  # 6.5 hours trading day
    t_fraction = minutes_to_expiry / total_minutes
    t_fraction = max(t_fraction, 0.001)

    return abs(daily_theta) / math.sqrt(t_fraction)
