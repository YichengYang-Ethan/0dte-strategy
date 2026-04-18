"""4-tier OOS validation on full 824-day dataset (2023-01-03 → 2026-04-16).

Tiers:
  Y2023     (250d)  2023-01-03 → 2023-12-29  — NEWEST data, never seen during design
  EXT_OOS   (345d)  2024-01-02 → 2025-05-14  — designed under
  ORIG_OOS  (118d)  2025-05-15 → 2025-10-30  — held out during v3 design
  ORIG_IS   (114d)  2025-10-31 → 2026-04-16  — v3 design sample

Tests all 4 signal modes. Key question: does v5 / gex_or_mr survive 2023?
2023 was a very different regime (high rates, mini banking crisis, regional
banks, yield curve inversion, bull rally Q4).
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date
import numpy as np
import pandas as pd
import logging
logging.basicConfig(level=logging.WARNING)

from src.backtest.engine import BacktestConfig, BacktestEngine

Y2023_START = date(2023, 1, 1)
EXT_OOS_START = date(2024, 1, 1)
ORIG_OOS_START = date(2025, 5, 15)
ORIG_IS_START = date(2025, 10, 31)


def bucket(d):
    if d >= ORIG_IS_START: return "ORIG_IS"
    if d >= ORIG_OOS_START: return "ORIG_OOS"
    if d >= EXT_OOS_START: return "EXT_OOS"
    return "Y2023"


def metrics(df, label):
    if df.empty:
        print(f"{label:12s} empty"); return
    wins = (df["pnl"] > 0).sum()
    pf_den = -df[df["pnl"] < 0]["pnl"].sum()
    pf = df[df["pnl"] > 0]["pnl"].sum() / pf_den if pf_den > 0 else float("inf")
    cum = df["pnl"].cumsum().values
    peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    sharpe = df["pnl"].mean() / df["pnl"].std() * np.sqrt(252) if df["pnl"].std() > 0 else 0
    print(f"{label:12s} | N={len(df):3d} WR={wins/len(df)*100:5.1f}% "
          f"PnL=${df['pnl'].sum():+7.0f} PF={pf:.2f} DD=${dd:+.0f} Sh={sharpe:.2f}")


for mode in ["gex", "mr", "gex_or_mr", "gex_and_mr"]:
    cfg = BacktestConfig(signal_mode=mode, contracts_per_trade=1)
    df = BacktestEngine(cfg).run("data/historical/spy", mode="swing_1dte")
    if df.empty:
        print(f"\n=== {mode} empty ==="); continue
    df["td"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.date
    df["bucket"] = df["td"].apply(bucket)
    print(f"\n=== {mode} ===")
    for b in ["Y2023", "EXT_OOS", "ORIG_OOS", "ORIG_IS", "ALL"]:
        sub = df if b == "ALL" else df[df["bucket"] == b]
        metrics(sub, b)
