"""0DTE options execution via IBKR."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from ib_insync import IB, Contract, LimitOrder, MarketOrder, Option, Trade

from src.risk.manager import RiskManager, RiskParams
from src.signal.generator import TradeSignal

logger = logging.getLogger(__name__)


@dataclass
class PositionState:
    trade: Trade
    contract: Contract
    entry_price: float
    entry_time: datetime
    signal: TradeSignal
    size: int
    status: str = "OPEN"  # OPEN, CLOSED
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: Optional[float] = None


class ZeroDTETrader:
    def __init__(
        self,
        ib: IB,
        risk: RiskManager,
        underlying: str = "SPY",
        paper: bool = True,
    ):
        self.ib = ib
        self.risk = risk
        self.underlying = underlying
        self.paper = paper
        self.positions: list[PositionState] = []
        self.daily_pnl = 0.0
        self.daily_trades = 0

    def execute(self, signal: TradeSignal, spot: float) -> Optional[PositionState]:
        """Place a 0DTE trade based on signal."""
        if signal.direction == "NEUTRAL" or signal.confidence < 0.6:
            return None

        # Risk checks
        if not self.risk.can_trade(self.daily_pnl, self.daily_trades):
            logger.warning("Risk limit reached, skipping trade")
            return None

        today = datetime.now().strftime("%Y%m%d")

        if signal.direction == "BULLISH":
            # OTM call, ~0.3% above spot
            strike = self._round_strike(spot * 1.003)
            right = "C"
        else:
            strike = self._round_strike(spot * 0.997)
            right = "P"

        contract = Option(self.underlying, today, strike, right, "SMART")
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            logger.error(f"Failed to qualify contract: {contract}")
            return None
        contract = qualified[0]

        # Get current price
        ticker = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(2)

        if ticker.bid is None or ticker.ask is None or ticker.bid <= 0:
            logger.warning(f"No valid quote for {contract}: bid={ticker.bid} ask={ticker.ask}")
            self.ib.cancelMktData(contract)
            return None

        mid = (ticker.bid + ticker.ask) / 2
        spread = ticker.ask - ticker.bid

        # Skip if spread too wide (>30% of mid)
        if mid > 0 and spread / mid > 0.30:
            logger.warning(f"Spread too wide: {spread:.2f} / {mid:.2f} = {spread/mid:.1%}")
            self.ib.cancelMktData(contract)
            return None

        # Position size from risk manager
        size = self.risk.position_size(mid)

        # Limit order at mid + small offset toward ask
        limit_price = round(mid + spread * 0.1, 2)
        order = LimitOrder("BUY", size, limit_price)

        if self.paper:
            logger.info(f"[PAPER] BUY {size}x {contract.localSymbol} @ ${limit_price:.2f}")

        trade = self.ib.placeOrder(contract, order)
        self.ib.sleep(3)

        if trade.orderStatus.status not in ("Filled", "PreSubmitted", "Submitted"):
            logger.warning(f"Order not filled: {trade.orderStatus.status}")
            self.ib.cancelOrder(order)
            self.ib.cancelMktData(contract)
            return None

        fill_price = trade.orderStatus.avgFillPrice if trade.orderStatus.avgFillPrice else limit_price

        pos = PositionState(
            trade=trade,
            contract=contract,
            entry_price=fill_price,
            entry_time=datetime.now(),
            signal=signal,
            size=size,
        )
        self.positions.append(pos)
        self.daily_trades += 1

        logger.info(
            f"OPENED: {signal.direction} {size}x {contract.localSymbol} "
            f"@ ${fill_price:.2f} | target={signal.target} | reason={signal.reason}"
        )
        return pos

    def manage_position(self, pos: PositionState) -> bool:
        """
        Check exit conditions. Returns True if position was closed.

        Exit rules:
        1. Take profit: +100%
        2. Stop loss: -50%
        3. Time stop: 30 min before close (3:30 PM ET)
        4. Signal reversal: external caller can force close
        """
        if pos.status == "CLOSED":
            return False

        ticker = self.ib.reqMktData(pos.contract, "", False, False)
        self.ib.sleep(1)

        current_mid = (ticker.bid + ticker.ask) / 2 if ticker.bid and ticker.ask else 0
        if current_mid <= 0:
            return False

        pnl_pct = (current_mid - pos.entry_price) / pos.entry_price
        now = datetime.now()

        exit_reason = None

        # Rule 1: Take profit at +100%
        if pnl_pct >= 1.0:
            exit_reason = "TAKE_PROFIT_100PCT"

        # Rule 2: Stop loss at -50%
        elif pnl_pct <= -0.5:
            exit_reason = "STOP_LOSS_50PCT"

        # Rule 3: Time stop at 3:30 PM ET
        elif now.hour == 15 and now.minute >= 30:
            exit_reason = "TIME_STOP_330PM"

        # Rule 4: Been open > 2 hours with < 10% profit
        elif (now - pos.entry_time) > timedelta(hours=2) and pnl_pct < 0.10:
            exit_reason = "STALE_POSITION"

        if exit_reason:
            self._close_position(pos, current_mid, exit_reason)
            return True

        return False

    def force_close(self, pos: PositionState, reason: str = "FORCED"):
        """Force close a position (signal reversal, EOD, etc.)."""
        if pos.status == "CLOSED":
            return
        ticker = self.ib.reqMktData(pos.contract, "", False, False)
        self.ib.sleep(1)
        current = (ticker.bid + ticker.ask) / 2 if ticker.bid and ticker.ask else pos.entry_price
        self._close_position(pos, current, reason)

    def _close_position(self, pos: PositionState, exit_price: float, reason: str):
        order = MarketOrder("SELL", pos.size)
        self.ib.placeOrder(pos.contract, order)
        self.ib.sleep(2)

        pos.exit_price = exit_price
        pos.exit_reason = reason
        pos.pnl = (exit_price - pos.entry_price) * pos.size * 100
        pos.status = "CLOSED"
        self.daily_pnl += pos.pnl

        logger.info(
            f"CLOSED: {pos.contract.localSymbol} @ ${exit_price:.2f} | "
            f"PnL=${pos.pnl:.2f} ({(exit_price/pos.entry_price-1)*100:+.0f}%) | "
            f"reason={reason}"
        )

    def close_all(self, reason: str = "EOD"):
        """Close all open positions."""
        for pos in self.positions:
            if pos.status == "OPEN":
                self.force_close(pos, reason)

    def _round_strike(self, price: float) -> float:
        """Round to nearest valid strike (SPY = $1 increments)."""
        return round(price)
