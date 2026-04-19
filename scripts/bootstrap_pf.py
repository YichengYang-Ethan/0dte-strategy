"""Bootstrap 95% CI on Profit Factor for each signal mode.

Resamples trades with replacement 1000 times per mode × per bucket. Gives a
sense of whether "gex_or_mr PF 1.51" is statistically distinguishable from
"gex PF 1.43" or just noise.

Caveat: trades are treated as IID which is weak. Better would be block
bootstrap, but with 113-150 trades and signal rate ~1/week, serial correlation
is already modest.
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

def bucket(d):
    if d >= ORIG_IS_START: return "ORIG_IS"
    if d >= ORIG_OOS_START: return "ORIG_OOS"
    return "EXT_OOS"


def pf(pnls):
    wins = pnls[pnls > 0].sum()
    losses = -pnls[pnls < 0].sum()
    return wins / losses if losses > 0 else float("inf")


def boot_ci(pnls, reps=1000, seed=42):
    if len(pnls) < 10: return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    pfs = []
    for _ in range(reps):
        sample = rng.choice(pnls, size=len(pnls), replace=True)
        p = pf(sample)
        if np.isfinite(p): pfs.append(p)
    if not pfs: return (np.nan, np.nan, np.nan)
    pfs = np.array(pfs)
    return np.median(pfs), np.percentile(pfs, 2.5), np.percentile(pfs, 97.5)


def main():
    results = []
    for mode in ["gex", "mr", "gex_or_mr", "gex_and_mr"]:
        cfg = BacktestConfig(signal_mode=mode, contracts_per_trade=1)
        df = BacktestEngine(cfg).run("data/historical/spy", mode="swing_1dte")
        if df.empty: continue
        df["td"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.date
        df["bucket"] = df["td"].apply(bucket)
        for b in ["EXT_OOS", "ORIG_OOS", "ORIG_IS", "ALL"]:
            sub = df if b == "ALL" else df[df["bucket"] == b]
            if sub.empty: continue
            pnls = sub["pnl"].values
            actual_pf = pf(pnls)
            med, lo, hi = boot_ci(pnls)
            results.append({
                "mode": mode, "bucket": b, "N": len(sub),
                "actual_PF": actual_pf, "PF_med": med, "PF_2.5": lo, "PF_97.5": hi,
            })

    res = pd.DataFrame(results)
    print("Bootstrap 95% CI on Profit Factor (1000 reps)\n")
    print(res.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    print("\nKey check: does gex_or_mr CI exclude gex CI?")
    for b in ["EXT_OOS", "ORIG_OOS", "ORIG_IS", "ALL"]:
        gex_row = res[(res["mode"] == "gex") & (res["bucket"] == b)]
        or_row = res[(res["mode"] == "gex_or_mr") & (res["bucket"] == b)]
        if gex_row.empty or or_row.empty: continue
        gex_lo = gex_row.iloc[0]["PF_2.5"]
        gex_hi = gex_row.iloc[0]["PF_97.5"]
        or_lo = or_row.iloc[0]["PF_2.5"]
        or_hi = or_row.iloc[0]["PF_97.5"]
        overlap = not (or_lo > gex_hi or gex_lo > or_hi)
        print(f"  {b}: gex [{gex_lo:.2f},{gex_hi:.2f}] vs or [{or_lo:.2f},{or_hi:.2f}] → "
              f"{'OVERLAP (no sig diff)' if overlap else 'DISTINCT'}")


if __name__ == "__main__":
    main()
