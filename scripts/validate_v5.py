"""v5 validation: same strategy, real Theta Greeks instead of BSM-inverted.

Reads the v2-enriched parquets (which now have Theta official greeks + IV)
and reruns the v4 strategy. Same BacktestConfig, same rules.

Compares IS/ORIG_OOS/EXT_OOS to v4 baseline (saved pre-v5 for reference).

Kill criteria:
- If any bucket PF < 1.2, v5 is worse than v4 — flag for rollback
- If PF uniformly >= v4 levels, promote v5 to main
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

ORIG_IS_START = date(2025, 10, 31)
ORIG_OOS_START = date(2025, 5, 15)

V4_BASELINE = {
    "ORIG_IS":  {"N": 30,  "WR": 60.0, "PF": 1.77, "Sharpe": 3.18},
    "ORIG_OOS": {"N": 17,  "WR": 41.2, "PF": 1.77, "Sharpe": 3.56},
    "EXT_OOS":  {"N": 87,  "WR": 54.0, "PF": 1.23, "Sharpe": 0.92},
    "ALL":      {"N": 134, "WR": 53.7, "PF": 1.40, "Sharpe": 1.59},
}


def bucket(d):
    if d >= ORIG_IS_START: return "ORIG_IS"
    if d >= ORIG_OOS_START: return "ORIG_OOS"
    return "EXT_OOS"


def compute_metrics(df):
    if df.empty: return None
    wins = (df["pnl"] > 0).sum()
    pf_den = -df[df["pnl"] < 0]["pnl"].sum()
    pf = df[df["pnl"] > 0]["pnl"].sum() / pf_den if pf_den > 0 else float("inf")
    cum = df["pnl"].cumsum().values
    peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    sharpe = df["pnl"].mean() / df["pnl"].std() * np.sqrt(252) if df["pnl"].std() > 0 else 0
    return {"N": len(df), "WR": wins/len(df)*100, "PnL": float(df["pnl"].sum()),
            "PF": float(pf), "DD": dd, "Sharpe": float(sharpe)}


def main():
    cfg = BacktestConfig(contracts_per_trade=1)
    df = BacktestEngine(cfg).run("data/historical/spy", mode="swing_1dte")
    if df.empty:
        print("No trades"); return 1
    df["trade_date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.date
    df["bucket"] = df["trade_date"].apply(bucket)

    print("=" * 80)
    print("v5 vs v4 comparison (real Theta Greeks vs BSM-inverted)")
    print("=" * 80)
    all_pass = True
    for b in ["ORIG_IS", "ORIG_OOS", "EXT_OOS", "ALL"]:
        sub = df if b == "ALL" else df[df["bucket"] == b]
        m = compute_metrics(sub)
        v4 = V4_BASELINE[b]
        if m is None:
            print(f"{b:10s} empty")
            continue
        pf_delta = m["PF"] - v4["PF"]
        sharpe_delta = m["Sharpe"] - v4["Sharpe"]
        pass_flag = "✓" if m["PF"] >= 1.2 else "✗"
        if m["PF"] < 1.2:
            all_pass = False
        print(f"{b:10s} | N={m['N']:3d} WR={m['WR']:5.1f}% "
              f"PnL=${m['PnL']:+7.0f} PF={m['PF']:.2f} (v4={v4['PF']:.2f} Δ={pf_delta:+.2f}) "
              f"Sharpe={m['Sharpe']:.2f} (Δ={sharpe_delta:+.2f}) {pass_flag}")

    print()
    if all_pass:
        print("VERDICT: v5 passes 1.2 floor on all buckets — data upgrade safe")
    else:
        print("VERDICT: v5 FAILS 1.2 floor somewhere — investigate regression")
    return 0 if all_pass else 2


if __name__ == "__main__":
    sys.exit(main())
