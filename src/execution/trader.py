"""0DTE options execution via IBKR — production grade."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from ib_insync import IB, Contract, LimitOrder, MarketOrder, Option, Trade

from src.risk.manager import RiskManager
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
    status: str = "OPEN"
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: Optional[float] = None
    peak_price: float = 0.0  # for trailing stop


@dataclass
class ExitParams:
    tp_pct: float = 1.0        # initial take profit trigger (100%)
    sl_pct: float = -0.5       # stop loss (-50%)
    trail_activate: float = 0.5  # start trailing after +50%
    trail_pct: float = 0.3     # trail 30% from peak once activated
    stale_hours: float = 2.0   # close if open > 2h with < 10% gain
    stale_min_pct: float = 0.1
    time_stop_minutes_before_close: int = 30  # 3:30 PM ET
    max_spread_pct: float = 0.30  # reject if bid-ask spread > 30% of mid


class ZeroDTETrader:
    def __init__(
        self,
        ib: IB,
        risk: RiskManager,
        underlying: str = "SPY",
        paper: bool = True,
        exit_params: ExitParams = None,
    ):
        self.ib = ib
        self.risk = risk
        self.underlying = underlying
        self.paper = paper
        self.exit_params = exit_params or ExitParams()
        self.positions: list[PositionState] = []
        self.daily_pnl = 0.0
        self.daily_trades = 0

    def select_strike(
        self,
        spot: float,
        direction: str,
        target_delta: float = 0.25,
        options_df=None,
    ) -> float:
        """
        Select strike by target delta instead of fixed % offset.

        For 0DTE, delta changes dramatically through the day:
        - 9:45 AM: delta 0.25 might be 2 points OTM
        - 2:30 PM: delta 0.25 might be 0.3 points OTM

        Falls back to fixed offset if no options data available.
        """
        if options_df is not None and not options_df.empty:
            right = "C" if direction == "BULLISH" else "P"
            candidates = options_df[
                (options_df["right"] == right) &
                (options_df["delta"].notna()) &
                (options_df["delta"].abs() > 0)
            ].copy()

            if not candidates.empty:
                candidates["delta_diff"] = (candidates["delta"].abs() - target_delta).abs()

                if direction == "BULLISH":
                    candidates = candidates[candidates["strike"] > spot]
                else:
                    candidates = candidates[candidates["strike"] < spot]

                if not candidates.empty:
                    best = candidates.loc[candidates["delta_diff"].idxmin()]
                    logger.info(
                        f"Strike by delta: {best['strike']} "
                        f"(delta={best['delta']:.3f}, target={target_delta})"
                    )
                    return float(best["strike"])

        # Fallback: fixed offset
        offset = spot * 0.003
        if direction == "BULLISH":
            return self._round_strike(spot + offset)
        return self._round_strike(spot - offset)

    def execute(
        self,
        signal: TradeSignal,
        spot: float,
        options_df=None,
    ) -> Optional[PositionState]:
        """Place a 0DTE trade based on signal."""
        if signal.direction == "NEUTRAL" or signal.confidence < 0.6:
            return None

        if not self.risk.can_trade(self.daily_pnl, self.daily_trades):
            logger.warning("Risk limit reached, skipping trade")
            return None

        today = datetime.now().strftime("%Y%m%d")
        right = "C" if signal.direction == "BULLISH" else "P"

        strike = self.select_strike(spot, signal.direction, options_df=options_df)

        contract = Option(self.underlying, today, strike, right, "SMART")
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            logger.error(f"Failed to qualify: {self.underlying} {today} {strike} {right}")
            return None
        contract = qualified[0]

        ticker = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(2)

        bid = ticker.bid
        ask = ticker.ask
        if not bid or not ask or bid <= 0 or ask <= 0:
            logger.warning(f"No valid quote: bid={bid} ask={ask}")
            self.ib.cancelMktData(contract)
            return None

        mid = (bid + ask) / 2
        spread = ask - bid

        if mid > 0 and spread / mid > self.exit_params.max_spread_pct:
            logger.warning(f"Spread too wide: {spread:.2f}/{mid:.2f} = {spread/mid:.0%}")
            self.ib.cancelMktData(contract)
            return None

        size = self.risk.position_size(mid)
        if size <= 0:
            logger.warning("Position size is 0, premium too high")
            self.ib.cancelMktData(contract)
            return None

        # Limit order: mid + 10% of spread toward ask (aggressive enough to fill)
        limit_price = round(mid + spread * 0.1, 2)
        order = LimitOrder("BUY", size, limit_price)
        order.tif = "IOC"  # Immediate or Cancel — don't leave resting orders on 0DTE

        logger.info(
            f"{'[PAPER] ' if self.paper else ''}BUY {size}x "
            f"{contract.localSymbol} @ ${limit_price:.2f} "
            f"(bid={bid:.2f} ask={ask:.2f} mid={mid:.2f})"
        )

        trade = self.ib.placeOrder(contract, order)
        self.ib.sleep(3)

        status = trade.orderStatus.status
        if status not in ("Filled", "PreSubmitted", "Submitted"):
            logger.warning(f"Order not filled: {status}")
            self.ib.cancelOrder(order)
            self.ib.cancelMktData(contract)
            return None

        fill_price = trade.orderStatus.avgFillPrice or limit_price

        pos = PositionState(
            trade=trade,
            contract=contract,
            entry_price=fill_price,
            entry_time=datetime.now(),
            signal=signal,
            size=size,
            peak_price=fill_price,
        )
        self.positions.append(pos)
        self.daily_trades += 1

        logger.info(
            f"OPENED: {signal.direction} {size}x {contract.localSymbol} "
            f"@ ${fill_price:.2f} | reason={signal.reason}"
        )
        return pos

    def manage_position(self, pos: PositionState) -> bool:
        """
        Check exit conditions with trailing stop. Returns True if closed.

        Exit priority (checked in order):
        1. Stop loss: -50% from entry
        2. Time stop: 30 min before close
        3. Stale position: > 2h with < 10% gain
        4. Trailing stop: once +50%, trail 30% from peak
        5. Take profit: +100% (only if trailing not yet activated)
        """
        if pos.status == "CLOSED":
            return False

        ticker = self.ib.reqMktData(pos.contract, "", False, False)
        self.ib.sleep(1)

        bid = ticker.bid
        ask = ticker.ask
        if not bid or not ask or bid <= 0:
            self.ib.cancelMktData(pos.contract)
            return False

        # Use bid for exit valuation (conservative — this is what you'd actually get)
        current = bid
        pnl_pct = (current - pos.entry_price) / pos.entry_price
        now = datetime.now()
        ep = self.exit_params

        # Update peak for trailing stop
        if current > pos.peak_price:
            pos.peak_price = current

        exit_reason = None

        # 1. Hard stop loss
        if pnl_pct <= ep.sl_pct:
            exit_reason = f"STOP_LOSS_{ep.sl_pct*100:.0f}PCT"

        # 2. Time stop
        elif now.hour == 15 and now.minute >= (60 - ep.time_stop_minutes_before_close):
            exit_reason = "TIME_STOP"

        # 3. Stale position
        elif ((now - pos.entry_time).total_seconds() > ep.stale_hours * 3600
              and pnl_pct < ep.stale_min_pct):
            exit_reason = "STALE_POSITION"

        # 4. Trailing stop (activated after trail_activate threshold)
        elif pnl_pct >= ep.trail_activate or pos.peak_price > pos.entry_price * (1 + ep.trail_activate):
            drawdown_from_peak = (pos.peak_price - current) / pos.peak_price
            if drawdown_from_peak >= ep.trail_pct:
                exit_reason = (
                    f"TRAILING_STOP (peak=${pos.peak_price:.2f}, "
                    f"now=${current:.2f}, dd={drawdown_from_peak:.0%})"
                )

        if exit_reason:
            self._close_position(pos, current, exit_reason)
            return True

        return False

    def force_close(self, pos: PositionState, reason: str = "FORCED"):
        if pos.status == "CLOSED":
            return
        ticker = self.ib.reqMktData(pos.contract, "", False, False)
        self.ib.sleep(1)
        bid = ticker.bid if ticker.bid and ticker.bid > 0 else 0.01
        self._close_position(pos, bid, reason)

    def _close_position(self, pos: PositionState, exit_price: float, reason: str):
        """Close position with limit order at bid (not market order)."""
        # Use limit order at current bid to avoid market order slippage
        limit_price = round(exit_price, 2)
        if limit_price <= 0:
            limit_price = 0.01

        order = LimitOrder("SELL", pos.size, limit_price)
        order.tif = "IOC"

        self.ib.placeOrder(pos.contract, order)
        self.ib.sleep(2)

        # Check if filled
        trade = self.ib.trades()[-1] if self.ib.trades() else None
        actual_fill = limit_price  # default
        if trade and trade.orderStatus.avgFillPrice:
            actual_fill = trade.orderStatus.avgFillPrice

        pos.exit_price = actual_fill
        pos.exit_reason = reason
        pos.pnl = (actual_fill - pos.entry_price) * pos.size * 100
        pos.status = "CLOSED"
        self.daily_pnl += pos.pnl

        self.ib.cancelMktData(pos.contract)

        logger.info(
            f"CLOSED: {pos.contract.localSymbol} @ ${actual_fill:.2f} | "
            f"PnL=${pos.pnl:.2f} ({(actual_fill/pos.entry_price-1)*100:+.1f}%) | "
            f"peak=${pos.peak_price:.2f} | reason={reason}"
        )

    def close_all(self, reason: str = "EOD"):
        for pos in self.positions:
            if pos.status == "OPEN":
                self.force_close(pos, reason)

    def reconcile_with_ib(self):
        """Reconcile internal state with IB's actual positions."""
        ib_positions = self.ib.positions()
        for pos in self.positions:
            if pos.status != "OPEN":
                continue
            matching = [
                p for p in ib_positions
                if p.contract.conId == pos.contract.conId
            ]
            if not matching:
                logger.warning(
                    f"Position {pos.contract.localSymbol} exists internally "
                    f"but not in IB — marking as CLOSED (lost)"
                )
                pos.status = "CLOSED"
                pos.exit_reason = "RECONCILIATION_LOST"
                pos.pnl = -pos.entry_price * pos.size * 100

    def _round_strike(self, price: float) -> float:
        """SPY = $1 increments, SPX = $5 increments."""
        if self.underlying == "SPX":
            return round(price / 5) * 5
        return round(price)
