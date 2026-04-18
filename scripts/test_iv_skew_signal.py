"""v10: IV skew signal test.

Hypothesis: high put-call IV skew indicates fear pricing. Historically (per
Bollerslev/Todorov, Bakshi/Kapadia/Madan), elevated skew is often followed by
short-term bounces as fear premium unwinds.

Signal: on day N EOD, compute IV_skew = IV(OTM_put) - IV(OTM_call) at
symmetric moneyness (e.g., 98% put vs 102% call). If skew above tercile
threshold, buy 0.70Δ 1DTE call.

Test with 3-tier OOS. Also test: is skew independent of 1-day return (MR proxy)?
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


def compute_skew(bar, spot, target_exp):
    """IV at 98% put minus IV at 102% call, for target expiry."""
    near = bar[bar["expiry"] == target_exp]
    if near.empty: return None
    call_target = spot * 1.02
    put_target = spot * 0.98
    calls = near[(near["right"] == "C") & (near["iv"] > 0)]
    puts = near[(near["right"] == "P") & (near["iv"] > 0)]
    if calls.empty or puts.empty: return None
    call_iv = float(calls.iloc[(calls["strike"] - call_target).abs().argmin()]["iv"])
    put_iv = float(puts.iloc[(puts["strike"] - put_target).abs().argmin()]["iv"])
    return put_iv - call_iv


def main():
    files = sorted(Path("data/historical/spy").glob("*.parquet"))
    fill = FillSimulator()

    spots = {}
    for fp in files:
        try:
            df = pd.read_parquet(fp, columns=["spot"])
            if not df.empty and "spot" in df.columns:
                s = df["spot"].dropna()
                if not s.empty: spots[datetime.strptime(fp.stem, "%Y%m%d").date()] = float(s.iloc[0])
        except Exception: pass
    dates_sorted = sorted(spots.keys())
    def r1d(d):
        idx = dates_sorted.index(d)
        return (spots[d] - spots[dates_sorted[idx-1]]) / spots[dates_sorted[idx-1]] * 100 if idx >= 1 else None

    rows = []
    for i, fp in enumerate(files[:-1]):
        try:
            d = datetime.strptime(fp.stem, "%Y%m%d").date()
            d_next = datetime.strptime(files[i+1].stem, "%Y%m%d").date()
        except ValueError: continue
        bar = pd.read_parquet(fp)
        if bar.empty or "spot" not in bar.columns: continue
        spot = float(bar["spot"].dropna().iloc[0])
        target_exp = d_next.strftime("%Y%m%d")
        skew = compute_skew(bar, spot, target_exp)
        if skew is None: continue

        # Trade: just buy the 0.70Δ 1DTE call unconditionally (test skew tercile filter later)
        cand = bar[(bar["expiry"] == target_exp) & (bar["right"] == "C") &
                   (bar["bid"] > 0) & (bar["ask"] > 0) & (bar["delta"].abs() > 0.05)]
        if cand.empty: continue
        r = cand.assign(dd=(cand["delta"].abs() - 0.70).abs()).sort_values("dd").iloc[0]
        f = fill.simulate_entry(float(r["bid"]), float(r["ask"]), "BUY",
                                datetime.combine(d, datetime.min.time()).replace(hour=13))
        if not f.filled: continue
        next_bar = pd.read_parquet(files[i+1])
        ns = float(next_bar["spot"].dropna().iloc[0]) if "spot" in next_bar.columns else spot
        pnl = (max(ns - float(r["strike"]), 0) - f.fill_price) * 100
        rows.append({"d": d, "bucket": bucket(d), "skew": skew, "r1d": r1d(d), "pnl": pnl})

    df = pd.DataFrame(rows)
    print(f"Total: {len(df)}  Skew stats: mean={df['skew'].mean():.3f}, std={df['skew'].std():.3f}")

    # Correlation check
    print(f"Corr(skew, next-day pnl): {df['skew'].corr(df['pnl']):.3f}")
    print(f"Corr(skew, r1d): {df['skew'].corr(df['r1d']):.3f}  ← is skew independent of MR?")

    def summary(label, s):
        if s.empty: return f"{label} empty"
        w = (s["pnl"] > 0).sum()
        pfd = -s[s["pnl"] < 0]["pnl"].sum()
        pf = s[s["pnl"] > 0]["pnl"].sum() / pfd if pfd > 0 else float("inf")
        return f"{label:30s} N={len(s):3d} WR={w/len(s)*100:5.1f}% PnL=${s['pnl'].sum():+.0f} PF={pf:.2f}"

    # Per-bucket skew terciles (walk-forward? No — this is just observational)
    print("\n=== Unconditional (all days): skew tercile vs PnL ===")
    df["st"] = pd.qcut(df["skew"], 3, labels=["low", "mid", "high"])
    for t in ["low", "mid", "high"]:
        print(summary(f"skew={t}", df[df["st"] == t]))

    # Test: skew high subset on 3-tier
    print("\n=== Skew HIGH tercile across buckets ===")
    high = df[df["st"] == "high"]
    for b in ["EXT_OOS", "ORIG_OOS", "ORIG_IS", "ALL"]:
        sub = high if b == "ALL" else high[high["bucket"] == b]
        print(summary(b, sub))

    # Combine with MR: skew HIGH AND r1d<-0.3
    print("\n=== Skew HIGH AND r1d<-0.3% ===")
    combo = df[(df["st"] == "high") & (df["r1d"] < -0.3)]
    for b in ["EXT_OOS", "ORIG_OOS", "ORIG_IS", "ALL"]:
        sub = combo if b == "ALL" else combo[combo["bucket"] == b]
        print(summary(b, sub))

    # Skew HIGH WITHOUT MR (independent alpha check)
    print("\n=== Skew HIGH AND r1d >= -0.3% (skew independent of MR?) ===")
    indep = df[(df["st"] == "high") & (df["r1d"] >= -0.3)]
    for b in ["EXT_OOS", "ORIG_OOS", "ORIG_IS", "ALL"]:
        sub = indep if b == "ALL" else indep[indep["bucket"] == b]
        print(summary(b, sub))


if __name__ == "__main__":
    main()
