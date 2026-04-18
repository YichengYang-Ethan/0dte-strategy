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

import numpy as np
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
    # target_delta=0.70 (ITM) balances trade count and profit factor best in the
    # 113-day diagnosis. OTM (0.25) bleeds too much theta on 1DTE holds.
    target_delta: float = 0.70
    contracts_per_trade: int = 10
    max_spread_pct: float = 0.30
    # VEX filter disabled by default — its apparent edge did not survive OOS
    # validation on 118 days (2025-05 → 2025-10). Kept as an option for
    # experimentation only.
    vex_filter: str = "none"
    vex_warmup_days: int = 60
    # Weekend-gap filter: initially looked spectacular (N=13 PF 8.19 on 232 days,
    # p=0.005) but FAILED extended OOS (N=21 PF 0.84 on 2024-01→2025-05). Kept as
    # disabled research flag — do NOT enable for production. Textbook overfit from
    # small-N multi-hypothesis testing.
    weekend_gap_only: bool = False


class BacktestEngine:
    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.fill_sim = FillSimulator(max_spread_pct=self.config.max_spread_pct)
        self.calendar = EventCalendar()
        self.trades: list[BacktestTrade] = []
        # Walk-forward VEX history for tercile classification (no lookahead)
        self._vex_history: list[float] = []

    def _vex_tercile(self, vex_today: float) -> str:
        """Classify today's VEX against expanding-window history.

        Returns 'low' | 'mid' | 'high' | 'warmup'. Uses only prior days' VEX
        (strictly in-sample at decision time) to avoid lookahead bias.
        """
        if len(self._vex_history) < max(self.config.vex_warmup_days, 3):
            return "warmup"
        hist = self._vex_history
        lo = float(np.quantile(hist, 1 / 3))
        hi = float(np.quantile(hist, 2 / 3))
        if vex_today <= lo:
            return "low"
        if vex_today >= hi:
            return "high"
        return "mid"

    def run(self, data_dir: str | Path, mode: str = "swing_1dte") -> pd.DataFrame:
        """
        Run backtest over all daily snapshot files in data_dir.

        mode="swing_1dte" (default): open at EOD of day N on 1DTE contracts,
        exit at EOD of day N+1 using realized intrinsic value. Appropriate
        when only daily EOD data is available (Theta Data Value plan).

        mode="intraday": synthetic intraday bars from single daily snapshot.
        Non-physical price path — intended only for smoke-testing plumbing.
        """
        data_dir = Path(data_dir)
        files = sorted(data_dir.glob("*.parquet"))

        if not files:
            logger.error(f"No parquet files found in {data_dir}")
            return pd.DataFrame()

        logger.info(f"Backtesting {len(files)} days from {data_dir} mode={mode}")

        if mode == "swing_1dte":
            for i in range(len(files) - 1):
                try:
                    self._run_swing_1dte(files[i], files[i + 1])
                except Exception as e:
                    logger.error(f"Error on {files[i].stem}: {e}")
                    continue
        else:
            for fpath in files:
                try:
                    self._run_day(fpath, fpath.stem)
                except Exception as e:
                    logger.error(f"Error on {fpath.stem}: {e}")
                    continue

        df = pd.DataFrame([vars(t) for t in self.trades])
        logger.info(f"Backtest complete: {len(self.trades)} trades over {len(files)} days")
        return df

    def _run_swing_1dte(self, signal_fpath: Path, exit_fpath: Path):
        """Open 1DTE position at day N EOD, exit at day N+1 EOD intrinsic.

        Designed for EOD-only data: generates one signal per day, trades the
        expiration that lands on the next trading day, and realizes P&L as
        intrinsic value at that expiration.
        """
        try:
            d = datetime.strptime(signal_fpath.stem, "%Y%m%d").date()
            d_next = datetime.strptime(exit_fpath.stem, "%Y%m%d").date()
        except ValueError:
            return

        day_info = self.calendar.classify_day(d)
        if day_info["mode"] == "NO_TRADE":
            return
        risk_mult = day_info["risk_multiplier"]

        # Experimental weekend-gap filter (disabled by default). Friday entry
        # (weekday 4) with Monday expiry holds over a non-trading weekend —
        # dealers cannot re-hedge accumulated short-gamma, producing a strong
        # put-wall bounce on reopen. See engine config comment for stats.
        if self.config.weekend_gap_only and d.weekday() != 4:
            return

        bar = pd.read_parquet(signal_fpath)
        if bar.empty:
            return

        spot = self._estimate_spot(bar)
        if spot <= 0:
            return

        bar = enrich_greeks(bar, spot, as_of=d)

        gex_profile = calculate_gex_profile(bar, spot)
        levels = identify_levels(gex_profile, spot)
        vanna = calculate_vanna_exposure(bar, spot)

        # Anchor signal time to EOD so CORE session classifier lets trades through
        signal_dt = datetime.combine(d, datetime.min.time()).replace(hour=13)
        sig = generate_signal(levels, vanna, signal_dt)

        # Record VEX AFTER computing the signal but BEFORE the filter — so today's
        # VEX is compared against history UP TO BUT NOT INCLUDING today.
        vex_bucket = self._vex_tercile(vanna.total_vanna)
        self._vex_history.append(vanna.total_vanna)

        if sig.direction == "NEUTRAL" or sig.confidence < self.config.min_confidence:
            return

        # VEX filter (walk-forward; no lookahead — uses only prior days for tercile)
        if self.config.vex_filter != "none" and vex_bucket != "warmup":
            if self.config.vex_filter == "avoid_high_bullish":
                if sig.direction == "BULLISH" and vex_bucket == "high":
                    return
            elif self.config.vex_filter == "only_aligned":
                if sig.direction == "BULLISH" and vex_bucket != "low":
                    return
                if sig.direction == "BEARISH" and vex_bucket != "high":
                    return

        # Restrict contract selection to the NEXT day's expiration (1DTE at entry)
        target_expiry = d_next.strftime("%Y%m%d")
        candidates = bar[bar["expiry"] == target_expiry]
        if candidates.empty:
            return

        contract = self._select_contract(candidates, sig.direction, spot)
        if contract is None:
            return

        bid = float(contract["bid"])
        ask = float(contract["ask"])
        fill = self.fill_sim.simulate_entry(bid, ask, "BUY", signal_dt)
        if not fill.filled:
            return

        size = max(1, int(self.config.contracts_per_trade * risk_mult))

        # Exit: intrinsic at next-day EOD (expiration)
        exit_bar = pd.read_parquet(exit_fpath)
        exit_spot_series = exit_bar["spot"].dropna() if "spot" in exit_bar.columns else pd.Series()
        exit_spot = float(exit_spot_series.iloc[0]) if not exit_spot_series.empty else spot

        strike = float(contract["strike"])
        is_call = contract["right"] == "C"
        intrinsic = max(exit_spot - strike, 0.0) if is_call else max(strike - exit_spot, 0.0)
        exit_price = max(intrinsic, 0.0)  # can be 0 if OTM at expiry

        entry = fill.fill_price
        pnl_per = exit_price - entry
        pnl = pnl_per * size * 100
        pnl_pct = pnl_per / entry if entry > 0 else 0

        dS = exit_spot - spot
        delta_pnl = float(contract.get("delta", 0)) * dS * size * 100
        gamma_pnl = 0.5 * float(contract.get("gamma", 0)) * dS**2 * size * 100
        theta_pnl = float(contract.get("theta", 0)) * 1.0 * size * 100  # 1 calendar day
        vega_pnl = 0.0  # IV change not modeled here

        exit_dt = datetime.combine(d_next, datetime.min.time()).replace(hour=16)
        exit_reason = "EXPIRY_ITM" if exit_price > 0.01 else "EXPIRY_OTM"

        trade = BacktestTrade(
            date=signal_fpath.stem,
            entry_time=str(signal_dt),
            exit_time=str(exit_dt),
            direction=sig.direction,
            strike=strike,
            right=contract["right"],
            entry_price=entry,
            exit_price=exit_price,
            entry_bid=bid, entry_ask=ask,
            exit_bid=exit_price, exit_ask=exit_price,
            entry_spot=spot, exit_spot=exit_spot,
            entry_slippage=fill.slippage, exit_slippage=0.0,
            size=size,
            pnl=pnl, pnl_pct=pnl_pct,
            exit_reason=exit_reason,
            regime=sig.regime, session=sig.time_session,
            confidence=sig.confidence, signal_reason=sig.reason,
            delta_pnl=delta_pnl, gamma_pnl=gamma_pnl,
            theta_pnl=theta_pnl, vega_pnl=vega_pnl,
        )
        self.trades.append(trade)
        logger.info(
            f"[BT] {signal_fpath.stem}→{exit_fpath.stem} {sig.direction} "
            f"{strike}{contract['right']} | ${entry:.2f}→${exit_price:.2f} | "
            f"PnL=${pnl:.0f} ({pnl_pct:+.0%}) | {exit_reason} | conf={sig.confidence}"
        )

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

        # For daily OI data (single timestamp per day), simulate intraday bars
        # by creating synthetic timestamps at key trading hours
        has_intraday = False
        if "timestamp" in day_df.columns:
            unique_ts = day_df["timestamp"].unique()
            if len(unique_ts) > 1:
                has_intraday = True

        if not has_intraday:
            # Single snapshot per day: simulate bars at 10:00, 11:00, 12:00, 13:00, 14:00
            synthetic_times = [
                datetime(d.year, d.month, d.day, h, 0)
                for h in [10, 11, 12, 13, 14]
            ]
            timestamps_dt = synthetic_times
        else:
            timestamps = sorted(day_df["timestamp"].unique())
            timestamps_dt = []
            for ts in timestamps:
                try:
                    timestamps_dt.append(pd.Timestamp(ts).to_pydatetime())
                except Exception:
                    timestamps_dt.append(datetime.fromisoformat(str(ts)))

        position = None
        traded_today = False  # once we enter one trade per day, skip new entries

        for now_dt in timestamps_dt:
            # Use full day data for each bar (OI doesn't change intraday)
            bar = day_df.copy()

            # Get spot from ATM option (average of ATM call bid+ask)
            spot = self._estimate_spot(bar)
            if spot <= 0:
                continue

            # Recompute Greeks from real IV, anchored to the trade date
            bar = enrich_greeks(bar, spot, as_of=d)

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
                    and position is None
                    and not traded_today):
                position = self._open_backtest_position(
                    sig, bar, spot, now_dt, date_str, risk_mult,
                )
                if position is not None:
                    traded_today = True

        # Force close at EOD if still open
        if position is not None:
            self._close_backtest_position(
                position, position["last_bar"], position["last_spot"],
                position["last_now"], date_str, "EOD_CLOSE",
            )

    def _estimate_spot(self, bar: pd.DataFrame) -> float:
        """Return underlying spot.

        Prefer real EOD close from `spot` column (set by data.enrich). Fall back
        to OI-weighted ATM estimate from nearest expiration only — LEAPS strikes
        dominate total OI and distort the full-chain estimate.
        """
        if bar.empty:
            return 0

        if "spot" in bar.columns:
            spot_vals = bar["spot"].dropna()
            if not spot_vals.empty and spot_vals.iloc[0] > 0:
                return float(spot_vals.iloc[0])

        # Fallback: use nearest expiry only to avoid LEAPS-strike contamination
        if "expiry" in bar.columns:
            nearest_exp = sorted(bar["expiry"].unique())[0]
            near = bar[bar["expiry"] == nearest_exp]
        else:
            near = bar

        oi_by_strike = near.groupby("strike")["open_interest"].sum()
        if oi_by_strike.empty or oi_by_strike.sum() == 0:
            return float(near["strike"].median())

        return float(oi_by_strike.idxmax())

    def _select_contract(
        self,
        bar: pd.DataFrame,
        direction: str,
        spot: float,
    ) -> Optional[pd.Series]:
        """Select contract by target delta.

        Picks the contract with |delta| closest to target_delta, irrespective of
        whether it's ITM or OTM. For target_delta>=0.55 on 1DTE this will almost
        always be ITM, and that's the intended behavior — empirically ITM 0.70Δ
        beats OTM on 1DTE swings because theta bleed is lower and intrinsic value
        cushions the premium.
        """
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
