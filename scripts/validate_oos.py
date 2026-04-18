"""Walk-forward + OOS validation.

Splits the enriched dataset into:
  IS  = original 114 days (2025-10-31 → 2026-04-16)  — used to design the strategy
  OOS = new ~118 days (2025-05-15 → 2025-10-30)      — never touched during design

Runs the SAME BacktestConfig on both. Reports IS vs OOS separately.

A strategy is considered valid only if OOS PF >= 1.5 (50% degradation budget vs IS).
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime
import numpy as np
import pandas as pd
import logging

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

from src.backtest.engine import BacktestConfig, BacktestEngine

IS_START = datetime(2025, 10, 31).date()

def metrics(df: pd.DataFrame, label: str):
    if df.empty:
        print(f"{label}: no trades")
        return
    wins = (df["pnl"] > 0).sum()
    pf_den = -df[df["pnl"] < 0]["pnl"].sum()
    pf = df[df["pnl"] > 0]["pnl"].sum() / pf_den if pf_den > 0 else float("inf")
    cum = df["pnl"].cumsum().values
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak).min()
    sharpe = df["pnl"].mean() / df["pnl"].std() * np.sqrt(252) if df["pnl"].std() > 0 else 0
    print(f"{label:15s} | N={len(df):3d} WR={wins/len(df)*100:5.1f}% "
          f"PnL=${df['pnl'].sum():+7.0f} avg=${df['pnl'].mean():+6.1f} "
          f"PF={pf:.2f} DD=${dd:+.0f} Sharpe={sharpe:.2f}")


def run(vex_filter: str = "avoid_high_bullish", warmup: int = 60, contracts: int = 1):
    """Run the full range; split trades into IS and OOS by date."""
    cfg = BacktestConfig(
        vex_filter=vex_filter,
        vex_warmup_days=warmup,
        contracts_per_trade=contracts,
    )
    eng = BacktestEngine(cfg)
    data_dir = "data/historical/spy"
    df = eng.run(data_dir, mode="swing_1dte")
    if df.empty:
        print("No trades"); return
    df["trade_date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.date

    oos = df[df["trade_date"] < IS_START].copy()
    is_ = df[df["trade_date"] >= IS_START].copy()

    print(f"\n=== {vex_filter} warmup={warmup} ({contracts} contract) ===")
    metrics(oos, "OOS")
    metrics(is_, "IS")
    metrics(df,  "ALL")

    # By month
    df["month"] = df["trade_date"].astype(str).str[:7]
    print("\nMonthly P&L:")
    print(df.groupby("month").agg(n=("pnl","count"), pnl=("pnl","sum"),
                                   wr=("pnl", lambda x: f"{(x>0).mean()*100:.0f}%")).to_string())


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--filter", default="avoid_high_bullish",
                   choices=["none", "avoid_high_bullish", "only_aligned"])
    p.add_argument("--warmup", type=int, default=60)
    p.add_argument("--contracts", type=int, default=1)
    args = p.parse_args()
    run(args.filter, args.warmup, args.contracts)
