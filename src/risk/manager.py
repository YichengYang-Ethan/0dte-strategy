"""Risk management for 0DTE options trading."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class RiskParams:
    max_daily_loss: float = 500.0
    max_position_size: int = 20
    max_premium_per_trade: float = 200.0
    max_trades_per_day: int = 5
    no_trade_before: str = "09:45"  # 15 min after open
    no_trade_after: str = "15:30"  # 30 min before close
    no_trade_events: list[str] = None  # FOMC, CPI, NFP days

    def __post_init__(self):
        if self.no_trade_events is None:
            self.no_trade_events = []


class RiskManager:
    def __init__(self, params: RiskParams = None):
        self.params = params or RiskParams()

    def can_trade(self, daily_pnl: float, daily_trades: int) -> bool:
        now = datetime.now()
        current_time = now.strftime("%H:%M")

        if current_time < self.params.no_trade_before:
            logger.info(f"Too early: {current_time} < {self.params.no_trade_before}")
            return False

        if current_time > self.params.no_trade_after:
            logger.info(f"Too late: {current_time} > {self.params.no_trade_after}")
            return False

        if daily_pnl <= -self.params.max_daily_loss:
            logger.warning(f"Daily loss limit hit: ${daily_pnl:.2f}")
            return False

        if daily_trades >= self.params.max_trades_per_day:
            logger.warning(f"Max trades reached: {daily_trades}")
            return False

        return True

    def position_size(self, premium: float) -> int:
        """Calculate position size based on max premium constraint."""
        if premium <= 0:
            return 0
        max_contracts = int(self.params.max_premium_per_trade / (premium * 100))
        return min(max(max_contracts, 1), self.params.max_position_size)
