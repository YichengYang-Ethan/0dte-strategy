"""Short v5: sell 0.70Δ 1DTE call on the same signal.

If our signal causes us to buy calls that lose money, the inverse (selling
calls) should make money. This tests whether v5 is directionally wrong or
just noise.

Also tests a short straddle variant (sell call + sell put) — premium capture
strategy that's direction-neutral.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date, datetime
import numpy as np
import pandas as pd
from src.gex.greeks import enrich_greeks
from src.gex.calculator import calculate_gex_profile, identify_levels
from src.backtest.fill_simulator import FillSimulator

Y2023_START = date(2023, 1, 1)
EXT_OOS_START = date(2024, 1, 1)
ORIG_OOS_START = date(2025, 5, 15)
ORIG_IS_START = date(2025, 10, 31)
def bucket(d):
    if d >= ORIG_IS_START: return "ORIG_IS"
    if d >= ORIG_OOS_START: return "ORIG_OOS"
    if d >= EXT_OOS_START: return "EXT_OOS"
    return "Y2023"

files = sorted(Path("data/historical/spy").glob("*.parquet"))
fill = FillSimulator()

# Preload spots
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


def simulate(mode: str = "short_call"):
    """mode: 'short_call' | 'short_straddle' | 'long_put'"""
    trades = []
    for i, fp in enumerate(files[:-1]):
        try:
            d = datetime.strptime(fp.stem, "%Y%m%d").date()
            d_next = datetime.strptime(files[i+1].stem, "%Y%m%d").date()
        except ValueError: continue
        bar = pd.read_parquet(fp)
        if bar.empty or "spot" not in bar.columns: continue
        spot = float(bar["spot"].dropna().iloc[0])
        bar = enrich_greeks(bar, spot, as_of=d)
        gex = calculate_gex_profile(bar, spot)
        lv = identify_levels(gex, spot)
        if not lv.call_wall or not lv.put_wall or lv.call_wall <= lv.put_wall: continue
        pos = (spot - lv.put_wall) / (lv.call_wall - lv.put_wall)
        if lv.regime != "NEGATIVE_GAMMA" or pos >= 0.15: continue

        target_exp = d_next.strftime("%Y%m%d")

        def pick(right, tgt_delta):
            cand = bar[(bar["expiry"]==target_exp)&(bar["right"]==right)&(bar["bid"]>0)&(bar["ask"]>0)&(bar["delta"].abs()>0.05)]
            if cand.empty: return None
            return cand.assign(dd=(cand["delta"].abs()-tgt_delta).abs()).sort_values("dd").iloc[0]

        call = pick("C", 0.70)
        put = pick("P", 0.70) if mode == "short_straddle" else None
        if call is None: continue
        if mode == "short_straddle" and put is None: continue

        # For SHORT position: we sell at bid (wait worse than mid), buy back at ask next day
        # Simulate: entry = bid (we receive), exit_basis = bid at next day (we buy back)
        # For short_call: PnL = entry_bid - intrinsic
        if mode in {"short_call", "short_straddle"}:
            c_bid = float(call["bid"])
            call_intrinsic_next = None  # compute at exit
            # Use mid - half-spread as the sell price (conservative)
            c_sell = max(c_bid - (float(call["ask"]) - c_bid) * 0.0, 0.01)  # no improvement assumption
            c_sell = (float(call["bid"]) + float(call["ask"])) / 2 - (float(call["ask"]) - float(call["bid"])) * 0.175  # mid minus quarter-spread
        # Long put
        if mode == "long_put":
            p = pick("P", 0.70)
            if p is None: continue
            f = fill.simulate_entry(float(p["bid"]), float(p["ask"]), "BUY",
                                    datetime.combine(d, datetime.min.time()).replace(hour=13))
            if not f.filled: continue
            next_bar = pd.read_parquet(files[i+1])
            ns = float(next_bar["spot"].dropna().iloc[0]) if "spot" in next_bar.columns else spot
            K = float(p["strike"])
            intr = max(K - ns, 0)
            pnl = (intr - f.fill_price) * 100
            trades.append({"d": d, "bucket": bucket(d), "pnl": pnl})
            continue

        next_bar = pd.read_parquet(files[i+1])
        ns = float(next_bar["spot"].dropna().iloc[0]) if "spot" in next_bar.columns else spot

        # Short call: receive c_sell, buy back at intrinsic
        c_K = float(call["strike"])
        c_intr = max(ns - c_K, 0)
        pnl = (c_sell - c_intr) * 100

        if mode == "short_straddle":
            p_sell = (float(put["bid"]) + float(put["ask"])) / 2 - (float(put["ask"]) - float(put["bid"])) * 0.175
            p_K = float(put["strike"])
            p_intr = max(p_K - ns, 0)
            pnl += (p_sell - p_intr) * 100

        trades.append({"d": d, "bucket": bucket(d), "pnl": pnl})
    return pd.DataFrame(trades)


def summary(lbl, s):
    if s.empty: return f"{lbl:12s} empty"
    w = (s["pnl"]>0).sum()
    pfd = -s[s["pnl"]<0]["pnl"].sum()
    pf = s[s["pnl"]>0]["pnl"].sum()/pfd if pfd>0 else float("inf")
    return f"{lbl:12s} N={len(s):3d} WR={w/len(s)*100:5.1f}% PnL=${s['pnl'].sum():+.0f} PF={pf:.2f}"


for m in ["short_call", "short_straddle", "long_put"]:
    print(f"\n=== Mode: {m} ===")
    df = simulate(m)
    for b in ["Y2023", "EXT_OOS", "ORIG_OOS", "ORIG_IS", "ALL"]:
        sub = df if b == "ALL" else df[df["bucket"] == b]
        print(summary(b, sub))
