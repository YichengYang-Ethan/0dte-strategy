"""v7 mechanism attribution: does the GEX signal add value OVER a pure
end-of-day reversal / 1-day mean-reversion baseline?

Motivated by Baltussen/Da/Soebhag (2024) finding that end-of-day moves reverse
overnight via retail-attention + short-seller channels, NOT gamma hedging.

Test:
  Baseline A: 'buy SPY after 1-day drop > X%' (pure mean reversion, no options)
  Baseline B: same but buy 0.70-delta 1DTE call (adds options convexity,
              no GEX signal)
  v4:        current rule (GEX pos<0.15 in NEG_GAMMA)
  v4 ∩ MR:   v4 AND 1-day drop > X%
  v4 \ MR:   v4 AND NO 1-day drop > X%   ← does GEX add value beyond MR?

If v4 \ MR (GEX signal without mean-reversion context) has PF ~1, it means my
strategy is just a proxy for mean reversion, and GEX isn't adding independent
alpha.
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

ORIG_IS_START = date(2025, 10, 31)
ORIG_OOS_START = date(2025, 5, 15)

def bucket(d):
    if d >= ORIG_IS_START: return "ORIG_IS"
    if d >= ORIG_OOS_START: return "ORIG_OOS"
    return "EXT_OOS"


def run():
    files = sorted(Path("data/historical/spy").glob("*.parquet"))
    fill = FillSimulator()

    # Pre-compute spots
    spots = {}
    for fp in files:
        try:
            df = pd.read_parquet(fp, columns=["spot"])
            if not df.empty and "spot" in df.columns:
                s = df["spot"].dropna()
                if not s.empty:
                    spots[datetime.strptime(fp.stem, "%Y%m%d").date()] = float(s.iloc[0])
        except Exception:
            pass
    dates_sorted = sorted(spots.keys())
    def ret_1d(d):
        idx = dates_sorted.index(d)
        if idx < 1: return None
        prev = dates_sorted[idx-1]
        return (spots[d] - spots[prev]) / spots[prev] * 100

    rows = []
    for i, fp in enumerate(files[:-1]):
        try:
            d = datetime.strptime(fp.stem, "%Y%m%d").date()
            d_next = datetime.strptime(files[i+1].stem, "%Y%m%d").date()
        except ValueError:
            continue
        bar = pd.read_parquet(fp)
        if bar.empty or "spot" not in bar.columns:
            continue
        spot = float(bar["spot"].dropna().iloc[0])
        bar = enrich_greeks(bar, spot, as_of=d)
        gex = calculate_gex_profile(bar, spot)
        lv = identify_levels(gex, spot)
        pos = None
        if lv.call_wall and lv.put_wall and lv.call_wall > lv.put_wall:
            pos = (spot - lv.put_wall) / (lv.call_wall - lv.put_wall)

        gex_trigger = (lv.regime == "NEGATIVE_GAMMA" and pos is not None and pos < 0.15)

        r1 = ret_1d(d)

        # Compute the 1DTE 0.70-delta call P&L if we entered
        target_exp = d_next.strftime("%Y%m%d")
        cand = bar[(bar["expiry"] == target_exp) & (bar["right"] == "C") &
                   (bar["bid"] > 0) & (bar["ask"] > 0) & (bar["delta"].abs() > 0.05)]
        pnl = None
        if not cand.empty:
            r_row = cand.assign(dd=(cand["delta"].abs()-0.70).abs()).sort_values("dd").iloc[0]
            f = fill.simulate_entry(float(r_row["bid"]), float(r_row["ask"]), "BUY",
                                    datetime.combine(d, datetime.min.time()).replace(hour=13))
            if f.filled:
                next_bar = pd.read_parquet(files[i+1])
                next_spot = float(next_bar["spot"].dropna().iloc[0]) if "spot" in next_bar.columns else spot
                intr = max(next_spot - float(r_row["strike"]), 0)
                pnl = (intr - f.fill_price) * 100

        rows.append({
            "d": d, "bucket": bucket(d), "spot": spot, "r1d": r1,
            "regime": lv.regime, "pos": pos, "gex_trigger": gex_trigger,
            "pnl_call": pnl,
        })

    df = pd.DataFrame(rows)

    def summary(label, sub):
        sub = sub.dropna(subset=["pnl_call"])
        if sub.empty: return f"{label:40s} empty"
        wins = (sub["pnl_call"] > 0).sum()
        pf_den = -sub[sub["pnl_call"] < 0]["pnl_call"].sum()
        pf = sub[sub["pnl_call"] > 0]["pnl_call"].sum() / pf_den if pf_den > 0 else float("inf")
        return (f"{label:40s} N={len(sub):3d} WR={wins/len(sub)*100:5.1f}% "
                f"PnL=${sub['pnl_call'].sum():+.0f} PF={pf:.2f}")

    # Different X% thresholds for mean-reversion trigger
    for thr in [-0.5, -1.0, -1.5]:
        print(f"\n=== 1-day drop threshold: {thr}% ===")
        mr = df["r1d"] < thr
        print(summary(f"Baseline MR (all r1d<{thr})", df[mr]))
        print(summary(f"v4 GEX only", df[df["gex_trigger"]]))
        print(summary(f"v4 ∩ MR (AND 1d<{thr})", df[df["gex_trigger"] & mr]))
        print(summary(f"v4 \\ MR (gex trigger + 1d>={thr})", df[df["gex_trigger"] & ~mr]))

    # Per-bucket attribution
    print("\n\n=== Per-bucket: 'v4 \\ MR' (is GEX independently useful?) ===")
    mr = df["r1d"] < -1.0
    for b in ["ORIG_IS", "ORIG_OOS", "EXT_OOS"]:
        sub = df[(df["bucket"] == b) & df["gex_trigger"] & ~mr]
        print(summary(f"{b}", sub))


if __name__ == "__main__":
    run()
