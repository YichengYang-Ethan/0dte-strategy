"""v8: Pure 1-day mean-reversion strategy validation (no GEX at all).

Rule: if prior-day SPY close-to-close return ≤ threshold, buy 0.70-delta 1DTE
call, hold to next-day intrinsic. No regime, no walls, no pos, no vanna.

Tests multiple thresholds on 574-day 3-tier OOS. Promote only if ALL 3 buckets
pass PF ≥ 1.3.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date, datetime
import numpy as np
import pandas as pd

from src.backtest.fill_simulator import FillSimulator

ORIG_IS_START = date(2025, 10, 31)
ORIG_OOS_START = date(2025, 5, 15)
def bucket(d):
    if d >= ORIG_IS_START: return "ORIG_IS"
    if d >= ORIG_OOS_START: return "ORIG_OOS"
    return "EXT_OOS"


def run(threshold_pct: float):
    files = sorted(Path("data/historical/spy").glob("*.parquet"))
    fill = FillSimulator()

    spots = {}
    for fp in files:
        try:
            df = pd.read_parquet(fp, columns=["spot"])
            if not df.empty and "spot" in df.columns:
                s = df["spot"].dropna()
                if not s.empty:
                    spots[datetime.strptime(fp.stem, "%Y%m%d").date()] = float(s.iloc[0])
        except Exception: pass
    dates_sorted = sorted(spots.keys())
    def ret_1d(d):
        idx = dates_sorted.index(d)
        if idx < 1: return None
        prev = dates_sorted[idx-1]
        return (spots[d] - spots[prev]) / spots[prev] * 100

    trades = []
    for i, fp in enumerate(files[:-1]):
        try:
            d = datetime.strptime(fp.stem, "%Y%m%d").date()
            d_next = datetime.strptime(files[i+1].stem, "%Y%m%d").date()
        except ValueError:
            continue
        r1 = ret_1d(d)
        if r1 is None or r1 >= threshold_pct:
            continue
        bar = pd.read_parquet(fp)
        if bar.empty or "spot" not in bar.columns:
            continue
        spot = float(bar["spot"].dropna().iloc[0])
        target_exp = d_next.strftime("%Y%m%d")
        cand = bar[(bar["expiry"] == target_exp) & (bar["right"] == "C") &
                   (bar["bid"] > 0) & (bar["ask"] > 0) & (bar["delta"].abs() > 0.05)]
        if cand.empty:
            continue
        r_row = cand.assign(dd=(cand["delta"].abs() - 0.70).abs()).sort_values("dd").iloc[0]
        f = fill.simulate_entry(float(r_row["bid"]), float(r_row["ask"]), "BUY",
                                datetime.combine(d, datetime.min.time()).replace(hour=13))
        if not f.filled: continue
        next_bar = pd.read_parquet(files[i+1])
        next_spot = float(next_bar["spot"].dropna().iloc[0]) if "spot" in next_bar.columns else spot
        pnl = (max(next_spot - float(r_row["strike"]), 0) - f.fill_price) * 100
        trades.append({"d": d, "bucket": bucket(d), "pnl": pnl, "r1d": r1})
    return pd.DataFrame(trades)


def summary(label, sub):
    if sub.empty: return f"{label:30s} empty"
    wins = (sub["pnl"] > 0).sum()
    pf_den = -sub[sub["pnl"] < 0]["pnl"].sum()
    pf = sub[sub["pnl"] > 0]["pnl"].sum() / pf_den if pf_den > 0 else float("inf")
    cum = sub["pnl"].cumsum().values
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak).min()
    sharpe = sub["pnl"].mean() / sub["pnl"].std() * np.sqrt(252) if sub["pnl"].std() > 0 else 0
    return (f"{label:30s} N={len(sub):3d} WR={wins/len(sub)*100:5.1f}% "
            f"PnL=${sub['pnl'].sum():+.0f} PF={pf:.2f} DD=${dd:+.0f} Sh={sharpe:.2f}")


if __name__ == "__main__":
    for thr in [-0.3, -0.5, -0.7, -1.0, -1.5]:
        print(f"\n=== Threshold r1d < {thr}% ===")
        df = run(thr)
        for b in ["EXT_OOS", "ORIG_OOS", "ORIG_IS", "ALL"]:
            sub = df if b == "ALL" else df[df["bucket"] == b]
            print(summary(b, sub))
