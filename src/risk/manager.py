"""Risk management for 0DTE options trading.

Position sizing: quarter-Kelly with VIX inverse scaling.
Capital per trade: 1-3% of account.
Same-day same-direction trades count as ONE position for sizing.

Reference: Baltussen et al. (JFE 2021), tastylive risk research
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class RiskParams:
    max_daily_loss: float = 500.0
    max_position_size: int = 20
    max_premium_per_trade: float = 200.0
    max_capital_pct_per_trade: float = 0.03  # 3% of account
    max_trades_per_day: int = 5
    no_trade_before: str = "09:45"
    no_trade_after: str = "15:30"
    vix_baseline: float = 16.0  # scale position size inversely to VIX
    kelly_fraction: float = 0.25  # quarter-Kelly


class RiskManager:
    def __init__(self, params: RiskParams = None, account_size: float = 10_000.0):
        self.params = params or RiskParams()
        self.account_size = account_size
        self.current_vix: float = 16.0
        self.event_risk_multiplier: float = 1.0
        self._same_day_directions: list[str] = []

    def update_vix(self, vix: float):
        self.current_vix = max(vix, 8.0)  # floor at 8 to avoid divide issues

    def set_event_multiplier(self, multiplier: float):
        self.event_risk_multiplier = multiplier

    def can_trade(self, daily_pnl: float, daily_trades: int) -> bool:
        now = datetime.now()
        current_time = now.strftime("%H:%M")

        if current_time < self.params.no_trade_before:
            logger.info(f"Too early: {current_time}")
            return False

        if current_time > self.params.no_trade_after:
            logger.info(f"Too late: {current_time}")
            return False

        if daily_pnl <= -self.params.max_daily_loss:
            logger.warning(f"Daily loss limit: ${daily_pnl:.2f}")
            return False

        if daily_trades >= self.params.max_trades_per_day:
            logger.warning(f"Max trades: {daily_trades}")
            return False

        return True

    def position_size(self, premium: float, direction: str = "") -> int:
        """
        Calculate position size with VIX scaling and event adjustment.

        Size = min(
            max_premium / (premium × 100),
            account × max_pct / (premium × 100),
            max_position_size,
        ) × vix_scale × event_multiplier

        Same-day same-direction trades treated as one position
        (correlated risk — Baltussen et al.).
        """
        if premium <= 0:
            return 0

        cost_per_contract = premium * 100

        # Base size from premium limit
        size_by_premium = int(self.params.max_premium_per_trade / cost_per_contract)

        # Size from capital percentage
        size_by_capital = int(
            (self.account_size * self.params.max_capital_pct_per_trade) / cost_per_contract
        )

        base_size = min(size_by_premium, size_by_capital, self.params.max_position_size)

        # VIX inverse scaling: high VIX → smaller size
        vix_scale = self.params.vix_baseline / self.current_vix
        vix_scale = max(0.3, min(vix_scale, 1.5))  # clamp [0.3, 1.5]

        # Event day scaling
        event_scale = self.event_risk_multiplier

        # Same-direction correlation penalty
        direction_penalty = 1.0
        if direction:
            same_dir_count = sum(1 for d in self._same_day_directions if d == direction)
            if same_dir_count >= 2:
                direction_penalty = 0.5  # 3rd+ same-direction trade gets half size
            elif same_dir_count >= 1:
                direction_penalty = 0.75

        final_size = int(base_size * vix_scale * event_scale * direction_penalty)

        if direction:
            self._same_day_directions.append(direction)

        return max(final_size, 1) if final_size > 0 else 0

    def kelly_size(
        self,
        win_prob: float,
        avg_win: float,
        avg_loss: float,
        premium: float,
    ) -> int:
        """
        Quarter-Kelly sizing for binary-like 0DTE payoffs.

        f* = (p × b - q) / b  where b = avg_win/avg_loss, q = 1-p
        Actual fraction = f* × kelly_fraction (0.25)

        Returns number of contracts.
        """
        if avg_loss == 0 or premium <= 0:
            return 0

        b = abs(avg_win / avg_loss)
        q = 1 - win_prob
        kelly_f = (win_prob * b - q) / b

        if kelly_f <= 0:
            return 0

        fraction = kelly_f * self.params.kelly_fraction
        dollar_bet = self.account_size * fraction
        contracts = int(dollar_bet / (premium * 100))

        return min(max(contracts, 1), self.params.max_position_size)

    def reset_daily(self):
        self._same_day_directions.clear()
