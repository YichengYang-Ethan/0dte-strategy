"""Backtesting engine for 0DTE GEX/Vanna strategy.

Replays historical options snapshots, calculates GEX/Vanna at each bar,
generates signals, simulates fills, and tracks P&L with attribution.

Data requirement: 15-min (or 1-min) options chain snapshots with
bid, ask, OI, volume, IV, and greeks per strike.

Reference: Barbon & Buraschi (2021), Baltussen et al. (JFE 2021)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from src.gex.calculator import calculate_gex_profile, calculate_vanna_exposure, identify_levels
from src.gex.greeks import enrich_greeks
from src.signal.generator import generate_signal, classify_session
from src.backtest.fill_simulator import FillSimulator, intraday_theta_decay
from src.risk.event_calendar import EventCalendar

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    date: str
    entry_time: str
    exit_time: str
    direction: str
    strike: float
    right: str
    entry_price: float
    exit_price: float
    entry_bid: float
    entry_ask: float
    exit_bid: float
    exit_ask: float
    entry_spot: float
    exit_spot: float
    entry_slippage: float
    exit_slippage: float
    size: int
    pnl: float
    pnl_pct: float
    exit_reason: str
    regime: str
    session: str
    confidence: float
    signal_reason: str
    # P&L attribution (Taylor expansion)
    delta_pnl: float = 0.0
    gamma_pnl: float = 0.0
    theta_pnl: float = 0.0
    vega_pnl: float = 0.0


@dataclass
class BacktestConfig:
    underlying: str = "SPY"
    bar_interval_minutes: int = 15
    tp_pct: float = 1.0
    sl_pct: float = -0.5
    trail_activate: float = 0.5
    trail_pct: float = 0.3
    stale_minutes: int = 120
    stale_min_pct: float = 0.10
    time_stop_minutes_before_close: int = 30
    min_confidence: float = 0.60
    target_delta: float = 0.25
    contracts_per_trade: int = 10
    max_spread_pct: float = 0.30


class BacktestEngine:
    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.fill_sim = FillSimulator(max_spread_pct=self.config.max_spread_pct)
        self.calendar = EventCalendar()
        self.trades: list[BacktestTrade] = []

    def run(self, data_dir: str | Path) -> pd.DataFrame:
        """
        Run backtest over all daily snapshot files in data_dir.

        Expected file format: {data_dir}/{YYYYMMDD}.parquet
        Each file contains 15-min snapshots with columns:
            timestamp, strike, right, expiry, bid, ask, volume,
            open_interest, gamma, delta, vega, theta, iv
        """
        data_dir = Path(data_dir)
        files = sorted(data_dir.glob("*.parquet"))

        if not files:
            logger.error(f"No parquet files found in {data_dir}")
            return pd.DataFrame()

        logger.info(f"Backtesting {len(files)} days from {data_dir}")

        for fpath in files:
            date_str = fpath.stem  # YYYYMMDD
            try:
                self._run_day(fpath, date_str)
            except Exception as e:
                logger.error(f"Error on {date_str}: {e}")
                continue

        df = pd.DataFrame([vars(t) for t in self.trades])
        logger.info(f"Backtest complete: {len(self.trades)} trades over {len(files)} days")
        return df

    def _run_day(self, fpath: Path, date_str: str):
        """Run backtest for a single day."""
        try:
            d = datetime.strptime(date_str, "%Y%m%d").date()
        except ValueError:
            return

        # Check event calendar
        day_info = self.calendar.classify_day(d)
        if day_info["mode"] == "NO_TRADE":
            return

        risk_mult = day_info["risk_multiplier"]

        day_df = pd.read_parquet(fpath)
        if day_df.empty:
            return

        # Get unique timestamps (bars)
        timestamps = sorted(day_df["timestamp"].unique())

        position = None

        for ts in timestamps:
            bar = day_df[day_df["timestamp"] == ts].copy()
            now = pd.Timestamp(ts)

            if hasattr(now, 'to_pydatetime'):
                now_dt = now.to_pydatetime()
            else:
                now_dt = datetime.fromisoformat(str(now))

            # Get spot from ATM option (average of ATM call bid+ask)
            spot = self._estimate_spot(bar)
            if spot <= 0:
                continue

            # Enrich with Vanna
            bar = enrich_greeks(bar, spot)

            # Calculate GEX
            gex_profile = calculate_gex_profile(bar, spot)
            levels = identify_levels(gex_profile, spot)
            vanna = calculate_vanna_exposure(bar, spot)

            # Manage existing position
            if position is not None:
                position = self._manage_backtest_position(
                    position, bar, spot, now_dt, date_str,
                )
                if position is None:
                    continue  # position was closed

            # Generate signal
            sig = generate_signal(levels, vanna, now_dt)

            if (sig.direction != "NEUTRAL"
                    and sig.confidence >= self.config.min_confidence
                    and position is None):
                position = self._open_backtest_position(
                    sig, bar, spot, now_dt, date_str, risk_mult,
                )

        # Force close at EOD if still open
        if position is not None:
            self._close_backtest_position(
                position, position["last_bar"], position["last_spot"],
                position["last_now"], date_str, "EOD_CLOSE",
            )

    def _estimate_spot(self, bar: pd.DataFrame) -> float:
        """Estimate underlying spot from option prices."""
        # Use midpoint of ATM call and put
        calls = bar[bar["right"] == "C"]
        if calls.empty:
            return 0

        # ATM = strike closest to average of all mid prices weighted by volume
        calls = calls.copy()
        calls["mid"] = (calls["bid"] + calls["ask"]) / 2
        # Find strike with highest volume (likely ATM)
        if "volume" in calls.columns and calls["volume"].sum() > 0:
            atm_idx = calls["volume"].idxmax()
        else:
            atm_idx = calls["mid"].idxmax()

        return float(calls.loc[atm_idx, "strike"])

    def _select_contract(
        self,
        bar: pd.DataFrame,
        direction: str,
        spot: float,
    ) -> Optional[pd.Series]:
        """Select contract by target delta."""
        right = "C" if direction == "BULLISH" else "P"
        candidates = bar[
            (bar["right"] == right) &
            (bar["delta"].notna()) &
            (bar["delta"].abs() > 0.05) &
            (bar["bid"] > 0) &
            (bar["ask"] > 0)
        ].copy()

        if candidates.empty:
            return None

        target = self.config.target_delta
        candidates["delta_diff"] = (candidates["delta"].abs() - target).abs()

        if direction == "BULLISH":
            candidates = candidates[candidates["strike"] > spot]
        else:
            candidates = candidates[candidates["strike"] < spot]

        if candidates.empty:
            return None

        return candidates.loc[candidates["delta_diff"].idxmin()]

    def _open_backtest_position(
        self, sig, bar, spot, now_dt, date_str, risk_mult,
    ) -> Optional[dict]:
        """Open a simulated position."""
        contract = self._select_contract(bar, sig.direction, spot)
        if contract is None:
            return None

        bid = float(contract["bid"])
        ask = float(contract["ask"])

        fill = self.fill_sim.simulate_entry(bid, ask, "BUY", now_dt)
        if not fill.filled:
            return None

        size = max(1, int(self.config.contracts_per_trade * risk_mult))

        return {
            "entry_time": str(now_dt),
            "entry_price": fill.fill_price,
            "entry_bid": bid,
            "entry_ask": ask,
            "entry_spot": spot,
            "entry_slippage": fill.slippage,
            "strike": float(contract["strike"]),
            "right": contract["right"],
            "direction": sig.direction,
            "regime": sig.regime,
            "session": sig.time_session,
            "confidence": sig.confidence,
            "signal_reason": sig.reason,
            "size": size,
            "peak_price": fill.fill_price,
            "entry_delta": float(contract.get("delta", 0)),
            "entry_gamma": float(contract.get("gamma", 0)),
            "entry_theta": float(contract.get("theta", 0)),
            "entry_vega": float(contract.get("vega", 0)),
            "entry_iv": float(contract.get("iv", 0)),
            "last_bar": bar,
            "last_spot": spot,
            "last_now": now_dt,
        }

    def _manage_backtest_position(
        self, pos: dict, bar: pd.DataFrame, spot: float,
        now_dt: datetime, date_str: str,
    ) -> Optional[dict]:
        """Check exit conditions on existing position."""
        # Find our contract in current bar
        contract_row = bar[
            (bar["strike"] == pos["strike"]) &
            (bar["right"] == pos["right"])
        ]

        if contract_row.empty:
            # Contract not in this bar (possibly expired worthless)
            self._close_backtest_position(
                pos, bar, spot, now_dt, date_str, "CONTRACT_EXPIRED",
                exit_price=0.01,
            )
            return None

        row = contract_row.iloc[0]
        bid = float(row["bid"]) if row["bid"] > 0 else 0.01
        ask = float(row["ask"]) if row["ask"] > 0 else bid

        # Use bid for position valuation (conservative)
        current = bid
        entry = pos["entry_price"]
        pnl_pct = (current - entry) / entry if entry > 0 else 0

        # Update peak
        if current > pos["peak_price"]:
            pos["peak_price"] = current

        # Update last known state
        pos["last_bar"] = bar
        pos["last_spot"] = spot
        pos["last_now"] = now_dt

        cfg = self.config
        exit_reason = None

        # 1. Stop loss
        if pnl_pct <= cfg.sl_pct:
            exit_reason = f"STOP_LOSS_{cfg.sl_pct*100:.0f}%"

        # 2. Time stop
        elif now_dt.hour == 15 and now_dt.minute >= (60 - cfg.time_stop_minutes_before_close):
            exit_reason = "TIME_STOP"

        # 3. Stale
        elif pos.get("entry_time"):
            entry_dt = datetime.fromisoformat(pos["entry_time"])
            if (now_dt - entry_dt).seconds > cfg.stale_minutes * 60 and pnl_pct < cfg.stale_min_pct:
                exit_reason = "STALE"

        # 4. Trailing stop
        elif pos["peak_price"] > entry * (1 + cfg.trail_activate):
            dd = (pos["peak_price"] - current) / pos["peak_price"]
            if dd >= cfg.trail_pct:
                exit_reason = f"TRAIL_STOP (peak=${pos['peak_price']:.2f} dd={dd:.0%})"

        if exit_reason:
            self._close_backtest_position(
                pos, bar, spot, now_dt, date_str, exit_reason,
            )
            return None

        return pos

    def _close_backtest_position(
        self, pos: dict, bar: pd.DataFrame, spot: float,
        now_dt: datetime, date_str: str, reason: str,
        exit_price: Optional[float] = None,
    ):
        """Close position and record trade."""
        if exit_price is None:
            contract_row = bar[
                (bar["strike"] == pos["strike"]) &
                (bar["right"] == pos["right"])
            ]
            if not contract_row.empty:
                row = contract_row.iloc[0]
                bid = float(row["bid"]) if row["bid"] > 0 else 0.01
                ask = float(row["ask"]) if row["ask"] > 0 else bid
                fill = self.fill_sim.simulate_exit(bid, ask, now_dt)
                exit_price = fill.fill_price
                exit_bid = bid
                exit_ask = ask
                exit_slippage = fill.slippage
            else:
                exit_price = 0.01
                exit_bid = 0.01
                exit_ask = 0.01
                exit_slippage = 0
        else:
            exit_bid = exit_price
            exit_ask = exit_price
            exit_slippage = 0

        entry = pos["entry_price"]
        pnl_per = exit_price - entry
        pnl = pnl_per * pos["size"] * 100
        pnl_pct = pnl_per / entry if entry > 0 else 0

        # P&L attribution (Taylor expansion approximation)
        dS = spot - pos["entry_spot"]
        delta_pnl = pos.get("entry_delta", 0) * dS * pos["size"] * 100
        gamma_pnl = 0.5 * pos.get("entry_gamma", 0) * dS**2 * pos["size"] * 100

        entry_dt = datetime.fromisoformat(pos["entry_time"])
        dt_hours = (now_dt - entry_dt).total_seconds() / 3600
        theta_pnl = pos.get("entry_theta", 0) * (dt_hours / 6.5) * pos["size"] * 100

        dIV = 0  # would need exit IV to compute
        vega_pnl = pos.get("entry_vega", 0) * dIV * pos["size"] * 100

        trade = BacktestTrade(
            date=date_str,
            entry_time=pos["entry_time"],
            exit_time=str(now_dt),
            direction=pos["direction"],
            strike=pos["strike"],
            right=pos["right"],
            entry_price=entry,
            exit_price=exit_price,
            entry_bid=pos["entry_bid"],
            entry_ask=pos["entry_ask"],
            exit_bid=exit_bid,
            exit_ask=exit_ask,
            entry_spot=pos["entry_spot"],
            exit_spot=spot,
            entry_slippage=pos["entry_slippage"],
            exit_slippage=exit_slippage,
            size=pos["size"],
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            regime=pos["regime"],
            session=pos["session"],
            confidence=pos["confidence"],
            signal_reason=pos["signal_reason"],
            delta_pnl=delta_pnl,
            gamma_pnl=gamma_pnl,
            theta_pnl=theta_pnl,
            vega_pnl=vega_pnl,
        )
        self.trades.append(trade)

        logger.info(
            f"[BT] {date_str} {pos['direction']} {pos['strike']}{pos['right']} | "
            f"${entry:.2f}→${exit_price:.2f} | PnL=${pnl:.2f} ({pnl_pct:+.0%}) | {reason}"
        )
