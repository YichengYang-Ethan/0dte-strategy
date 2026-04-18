"""Extended-OOS validation across the full 574-day dataset.

Splits:
  ORIG_OOS:     2025-05-15 → 2025-10-30 (118 days) — already used for v3 design
  ORIG_IS:      2025-10-31 → 2026-04-16 (114 days) — used for v3 design
  EXTENDED_OOS: 2024-01-02 → 2025-05-14 (~345 days) — held out, strategy frozen

Tests 2 configs:
  baseline: NEG_GAMMA + pos<0.3 → BULLISH, target_delta 0.70
  weekend:  same but weekend_gap_only=True (Friday entry → Monday expiry)

Overfit criterion: Extended-OOS PF ≥ 80% of ORIG design PF.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date
import numpy as np
import pandas as pd
import logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

from src.backtest.engine import BacktestConfig, BacktestEngine

ORIG_IS_START = date(2025, 10, 31)
ORIG_OOS_START = date(2025, 5, 15)  # start of 2nd-tier OOS
EXT_OOS_START = date(2024, 1, 1)     # start of 3rd-tier (new) OOS

def bucket(d):
    if d >= ORIG_IS_START: return "ORIG_IS"
    if d >= ORIG_OOS_START: return "ORIG_OOS"
    return "EXT_OOS"

def metrics(df, label):
    if df.empty:
        print(f"{label:12s} empty"); return
    wins = (df["pnl"] > 0).sum()
    pf_den = -df[df["pnl"] < 0]["pnl"].sum()
    pf = df[df["pnl"] > 0]["pnl"].sum() / pf_den if pf_den > 0 else float("inf")
    cum = df["pnl"].cumsum().values
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak).min()
    sharpe = df["pnl"].mean() / df["pnl"].std() * np.sqrt(252) if df["pnl"].std() > 0 else 0
    print(f"{label:12s} | N={len(df):3d} WR={wins/len(df)*100:5.1f}% "
          f"PnL=${df['pnl'].sum():+7.0f} avg=${df['pnl'].mean():+6.1f} "
          f"PF={pf:.2f} DD=${dd:+.0f} Sharpe={sharpe:.2f}")


def run(weekend_gap_only: bool):
    cfg = BacktestConfig(
        weekend_gap_only=weekend_gap_only,
        vex_filter="none",
        contracts_per_trade=1,
    )
    eng = BacktestEngine(cfg)
    df = eng.run("data/historical/spy", mode="swing_1dte")
    if df.empty:
        print("No trades"); return
    df["trade_date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.date
    df["bucket"] = df["trade_date"].apply(bucket)

    tag = "WEEKEND_GAP_ONLY" if weekend_gap_only else "BASELINE (all NEG_low_bounce)"
    print(f"\n=== {tag} ===")
    for lbl in ["EXT_OOS", "ORIG_OOS", "ORIG_IS", "ALL"]:
        sub = df if lbl == "ALL" else df[df["bucket"] == lbl]
        metrics(sub, lbl)

    # Monthly
    df["ym"] = df["trade_date"].astype(str).str[:7]
    monthly = df.groupby("ym").agg(n=("pnl","count"), pnl=("pnl","sum"),
                                    wr=("pnl", lambda x: (x>0).mean()))
    print(f"\nMonthly (N≥2 only):")
    print(monthly[monthly["n"] >= 2].to_string())
    return df


if __name__ == "__main__":
    base = run(weekend_gap_only=False)
    wknd = run(weekend_gap_only=True)
