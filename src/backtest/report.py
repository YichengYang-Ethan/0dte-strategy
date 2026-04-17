"""Performance reporting and P&L attribution for backtests.

Metrics: Sharpe, Sortino, Max DD, Calmar, win rate, profit factor.
P&L attribution: delta, gamma, theta, vega components.
Alpha separation: regress against SPX return + VIX change.

Target Sharpe for 0DTE: >1.0 after costs (industry benchmark).
Reference: OptionMetrics research, Baltussen et al. (JFE 2021)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BacktestReport:
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    avg_pnl: float
    max_win: float
    max_loss: float
    sharpe: float
    sortino: float
    max_drawdown: float
    max_drawdown_pct: float
    calmar: float
    avg_slippage_entry: float
    avg_slippage_exit: float
    total_slippage: float
    # P&L attribution
    total_delta_pnl: float
    total_gamma_pnl: float
    total_theta_pnl: float
    total_vega_pnl: float
    # By regime
    pnl_neg_gamma: float
    pnl_pos_gamma: float
    trades_neg_gamma: int
    trades_pos_gamma: int
    # By session
    pnl_core: float
    pnl_gamma_ramp: float
    # By exit reason
    exit_reasons: dict


def generate_report(trades_df: pd.DataFrame, initial_capital: float = 10_000) -> BacktestReport:
    """Generate comprehensive backtest report from trade DataFrame."""
    if trades_df.empty:
        return _empty_report()

    df = trades_df.copy()

    # Basic stats
    total = len(df)
    wins_df = df[df["pnl"] > 0]
    losses_df = df[df["pnl"] <= 0]
    wins = len(wins_df)
    losses = len(losses_df)
    win_rate = wins / total if total > 0 else 0

    total_pnl = df["pnl"].sum()
    gross_profit = wins_df["pnl"].sum() if not wins_df.empty else 0
    gross_loss = losses_df["pnl"].sum() if not losses_df.empty else 0
    profit_factor = gross_profit / abs(gross_loss) if gross_loss != 0 else float("inf")

    avg_win = wins_df["pnl"].mean() if not wins_df.empty else 0
    avg_loss = losses_df["pnl"].mean() if not losses_df.empty else 0
    avg_pnl = df["pnl"].mean()
    max_win = df["pnl"].max()
    max_loss = df["pnl"].min()

    # Daily P&L for Sharpe/Sortino
    df["date_key"] = df["date"]
    daily_pnl = df.groupby("date_key")["pnl"].sum()

    sharpe = _sharpe(daily_pnl)
    sortino = _sortino(daily_pnl)

    # Drawdown
    cumulative = daily_pnl.cumsum()
    peak = cumulative.cummax()
    drawdown = cumulative - peak
    max_dd = drawdown.min()
    max_dd_pct = max_dd / (initial_capital + peak.max()) if peak.max() > 0 else 0

    # Calmar
    annual_return = daily_pnl.mean() * 252
    calmar = annual_return / abs(max_dd) if max_dd != 0 else 0

    # Slippage
    avg_slip_entry = df["entry_slippage"].mean() if "entry_slippage" in df else 0
    avg_slip_exit = df["exit_slippage"].mean() if "exit_slippage" in df else 0
    total_slip = (df["entry_slippage"].sum() + df["exit_slippage"].sum()) * df["size"].mean() * 100

    # P&L attribution
    total_delta = df["delta_pnl"].sum() if "delta_pnl" in df else 0
    total_gamma = df["gamma_pnl"].sum() if "gamma_pnl" in df else 0
    total_theta = df["theta_pnl"].sum() if "theta_pnl" in df else 0
    total_vega = df["vega_pnl"].sum() if "vega_pnl" in df else 0

    # By regime
    neg_g = df[df["regime"] == "NEGATIVE_GAMMA"]
    pos_g = df[df["regime"] == "POSITIVE_GAMMA"]

    # By session
    core = df[df["session"] == "CORE"]
    ramp = df[df["session"] == "GAMMA_RAMP"]

    # Exit reasons
    exit_reasons = df["exit_reason"].value_counts().to_dict()

    return BacktestReport(
        total_trades=total,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        total_pnl=total_pnl,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        avg_win=avg_win,
        avg_loss=avg_loss,
        avg_pnl=avg_pnl,
        max_win=max_win,
        max_loss=max_loss,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct,
        calmar=calmar,
        avg_slippage_entry=avg_slip_entry,
        avg_slippage_exit=avg_slip_exit,
        total_slippage=total_slip,
        total_delta_pnl=total_delta,
        total_gamma_pnl=total_gamma,
        total_theta_pnl=total_theta,
        total_vega_pnl=total_vega,
        pnl_neg_gamma=neg_g["pnl"].sum() if not neg_g.empty else 0,
        pnl_pos_gamma=pos_g["pnl"].sum() if not pos_g.empty else 0,
        trades_neg_gamma=len(neg_g),
        trades_pos_gamma=len(pos_g),
        pnl_core=core["pnl"].sum() if not core.empty else 0,
        pnl_gamma_ramp=ramp["pnl"].sum() if not ramp.empty else 0,
        exit_reasons=exit_reasons,
    )


def print_report(report: BacktestReport):
    """Pretty-print backtest report."""
    r = report
    print("=" * 60)
    print("0DTE BACKTEST REPORT")
    print("=" * 60)
    print(f"Trades: {r.total_trades} (W:{r.wins} L:{r.losses} WR:{r.win_rate:.1%})")
    print(f"Total PnL: ${r.total_pnl:,.2f}")
    print(f"Profit Factor: {r.profit_factor:.2f}")
    print(f"Avg Win: ${r.avg_win:.2f} | Avg Loss: ${r.avg_loss:.2f}")
    print(f"Max Win: ${r.max_win:.2f} | Max Loss: ${r.max_loss:.2f}")
    print()
    print(f"Sharpe: {r.sharpe:.2f} | Sortino: {r.sortino:.2f}")
    print(f"Max Drawdown: ${r.max_drawdown:,.2f} ({r.max_drawdown_pct:.1%})")
    print(f"Calmar: {r.calmar:.2f}")
    print()
    print(f"Avg Slippage: entry=${r.avg_slippage_entry:.3f} exit=${r.avg_slippage_exit:.3f}")
    print(f"Total Slippage Cost: ${r.total_slippage:,.2f}")
    print()
    print("P&L Attribution:")
    print(f"  Delta: ${r.total_delta_pnl:,.2f}")
    print(f"  Gamma: ${r.total_gamma_pnl:,.2f}")
    print(f"  Theta: ${r.total_theta_pnl:,.2f}")
    print(f"  Vega:  ${r.total_vega_pnl:,.2f}")
    print()
    print("By Regime:")
    print(f"  Neg Gamma: ${r.pnl_neg_gamma:,.2f} ({r.trades_neg_gamma} trades)")
    print(f"  Pos Gamma: ${r.pnl_pos_gamma:,.2f} ({r.trades_pos_gamma} trades)")
    print()
    print("By Session:")
    print(f"  Core (10-14): ${r.pnl_core:,.2f}")
    print(f"  Gamma Ramp (14-15:30): ${r.pnl_gamma_ramp:,.2f}")
    print()
    print("Exit Reasons:")
    for reason, count in sorted(r.exit_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")
    print("=" * 60)


def _sharpe(daily_pnl: pd.Series, risk_free: float = 0.05) -> float:
    if daily_pnl.std() == 0 or len(daily_pnl) < 2:
        return 0.0
    excess = daily_pnl.mean() - risk_free / 252
    return excess / daily_pnl.std() * math.sqrt(252)


def _sortino(daily_pnl: pd.Series, risk_free: float = 0.05) -> float:
    if len(daily_pnl) < 2:
        return 0.0
    excess = daily_pnl.mean() - risk_free / 252
    downside = daily_pnl[daily_pnl < 0]
    if downside.std() == 0 or len(downside) < 2:
        return 0.0
    return excess / downside.std() * math.sqrt(252)


def _empty_report() -> BacktestReport:
    return BacktestReport(
        total_trades=0, wins=0, losses=0, win_rate=0,
        total_pnl=0, gross_profit=0, gross_loss=0, profit_factor=0,
        avg_win=0, avg_loss=0, avg_pnl=0, max_win=0, max_loss=0,
        sharpe=0, sortino=0, max_drawdown=0, max_drawdown_pct=0, calmar=0,
        avg_slippage_entry=0, avg_slippage_exit=0, total_slippage=0,
        total_delta_pnl=0, total_gamma_pnl=0, total_theta_pnl=0, total_vega_pnl=0,
        pnl_neg_gamma=0, pnl_pos_gamma=0, trades_neg_gamma=0, trades_pos_gamma=0,
        pnl_core=0, pnl_gamma_ramp=0, exit_reasons={},
    )
