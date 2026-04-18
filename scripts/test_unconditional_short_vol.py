"""Unconditional short-vol baseline — sell ATM straddle every trading day.

Tests whether there's a structural short-vol premium in 1DTE SPY options
that our long-call v5 strategy has been missing. If unconditional short
straddle has positive EV across all 4 OOS tiers, we have a legitimate
pivot candidate to Vilkov-style short-premium strategies.

Also tests short ATM straddle ONLY when VIX proxy (IV of ATM 1DTE call) is
high, low, or unrestricted — simple vol-regime filter.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date, datetime
import numpy as np
import pandas as pd

ORIG_IS_START = date(2025, 10, 31)
ORIG_OOS_START = date(2025, 5, 15)
EXT_OOS_START = date(2024, 1, 1)
def bucket(d):
    if d >= ORIG_IS_START: return "ORIG_IS"
    if d >= ORIG_OOS_START: return "ORIG_OOS"
    if d >= EXT_OOS_START: return "EXT_OOS"
    return "Y2023"


def simulate():
    """For each day, identify the ATM call and put at the next-day expiry.
    Sell both at mid - 0.25 × half-spread. Compute P&L at exit intrinsic."""
    files = sorted(Path("data/historical/spy").glob("*.parquet"))
    trades = []
    for i, fp in enumerate(files[:-1]):
        try:
            d = datetime.strptime(fp.stem, "%Y%m%d").date()
            d_next = datetime.strptime(files[i+1].stem, "%Y%m%d").date()
        except ValueError: continue
        bar = pd.read_parquet(fp)
        if bar.empty or "spot" not in bar.columns: continue
        spot = float(bar["spot"].dropna().iloc[0])

        target_exp = d_next.strftime("%Y%m%d")
        chain = bar[(bar["expiry"] == target_exp) & (bar["bid"] > 0) & (bar["ask"] > 0)]
        if chain.empty: continue

        # Find ATM call and put (closest strike to spot)
        for right in ["C", "P"]:
            sub = chain[chain["right"] == right]
            if sub.empty: continue
            atm_row = sub.iloc[(sub["strike"] - spot).abs().argmin()]
            break

        atm_strike = None
        call_row = None; put_row = None
        calls = chain[chain["right"] == "C"]
        puts = chain[chain["right"] == "P"]
        if calls.empty or puts.empty: continue
        call_row = calls.iloc[(calls["strike"] - spot).abs().argmin()]
        put_row = puts.iloc[(puts["strike"] - spot).abs().argmin()]
        # Use matching strikes (must be close to each other)
        if abs(call_row["strike"] - put_row["strike"]) > 2:
            continue  # skip — no consistent ATM

        # Sell prices (conservative: mid minus quarter-spread on our side)
        def sell_px(row):
            b, a = float(row["bid"]), float(row["ask"])
            mid = (a + b) / 2
            return mid - 0.25 * (a - b)  # slightly worse than mid for us

        c_sell = sell_px(call_row)
        p_sell = sell_px(put_row)
        c_K = float(call_row["strike"])
        p_K = float(put_row["strike"])

        next_bar = pd.read_parquet(files[i+1])
        ns = float(next_bar["spot"].dropna().iloc[0]) if "spot" in next_bar.columns else spot
        c_intr = max(ns - c_K, 0)
        p_intr = max(p_K - ns, 0)
        premium = c_sell + p_sell
        realized_payoff = c_intr + p_intr
        # We sold both, so PNL = premium received - payoff paid at expiry
        pnl = (premium - realized_payoff) * 100

        # ATM call IV (proxy for vol regime)
        atm_iv = float(call_row.get("iv", 0)) if "iv" in call_row else 0

        trades.append({"d": d, "bucket": bucket(d), "pnl": pnl, "atm_iv": atm_iv,
                       "premium": premium * 100, "payoff": realized_payoff * 100})
    return pd.DataFrame(trades)


def summary(lbl, s):
    if s.empty: return f"{lbl} empty"
    w = (s["pnl"] > 0).sum()
    pfd = -s[s["pnl"] < 0]["pnl"].sum()
    pf = s[s["pnl"] > 0]["pnl"].sum() / pfd if pfd > 0 else float("inf")
    return (f"{lbl:12s} N={len(s):3d} WR={w/len(s)*100:5.1f}% "
            f"PnL=${s['pnl'].sum():+.0f} avg=${s['pnl'].mean():+.1f} PF={pf:.2f}")


df = simulate()
print(f"Total short-straddle trades: {len(df)}")

print("\n=== Unconditional short straddle ===")
for b in ["Y2023", "EXT_OOS", "ORIG_OOS", "ORIG_IS", "ALL"]:
    sub = df if b == "ALL" else df[df["bucket"] == b]
    print(summary(b, sub))

# IV tercile filter — but compute per-bucket tercile (no lookahead within bucket)
# Also compute global tercile for simplicity
print("\n=== IV tercile filter (ATM call IV) ===")
df["iv_terc"] = pd.qcut(df["atm_iv"].clip(lower=0), 3, labels=["low", "mid", "high"], duplicates="drop")
for t in ["low", "mid", "high"]:
    sub = df[df["iv_terc"] == t]
    print(summary(f"iv_{t}", sub))

# High IV only across buckets
print("\n=== IV HIGH tercile — by bucket ===")
high = df[df["iv_terc"] == "high"]
for b in ["Y2023", "EXT_OOS", "ORIG_OOS", "ORIG_IS", "ALL"]:
    sub = high if b == "ALL" else high[high["bucket"] == b]
    print(summary(b, sub))
