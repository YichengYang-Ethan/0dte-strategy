"""Instrument sanity check (GPT Pro Day 4 task).

Question: does v5's signal predict SPY close-to-close returns at all?
If spot has no edge, kill the project. If spot has edge but the call loses,
change the instrument (maybe call spread) not the signal.

Tests on 824 days:
  Layer 1: v5 signal fires → next-day SPY close/close return (delta-one proxy)
  Layer 2: v5 signal fires → 0.70Δ call P&L (current production)
  Layer 3: v5 signal fires → ATM call spread (±$5) P&L (cheaper delta exposure)

Output: per-bucket WR/PF/mean-return for each layer.
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
EXT_OOS_START = date(2024, 1, 1)


def bucket(d):
    if d >= ORIG_IS_START: return "ORIG_IS"
    if d >= ORIG_OOS_START: return "ORIG_OOS"
    if d >= EXT_OOS_START: return "EXT_OOS"
    return "Y2023"


def main():
    files = sorted(Path("data/historical/spy").glob("*.parquet"))
    fill = FillSimulator()
    trades = []

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
        target_exp = d_next.strftime("%Y%m%d")

        # v5 signal decision
        bar_e = enrich_greeks(bar, spot, as_of=d)
        gex = calculate_gex_profile(bar_e, spot)
        lv = identify_levels(gex, spot)

        if not lv.call_wall or not lv.put_wall or lv.call_wall <= lv.put_wall:
            continue
        pos = (spot - lv.put_wall) / (lv.call_wall - lv.put_wall)
        if lv.regime != "NEGATIVE_GAMMA" or pos >= 0.15:
            continue

        # Signal fired. Record next-day outcome across 3 instruments.
        next_bar = pd.read_parquet(files[i+1])
        ns = float(next_bar["spot"].dropna().iloc[0]) if "spot" in next_bar.columns else spot

        # --- L1: SPY close/close return (100 shares for $-consistency) ---
        spot_ret_pct = (ns - spot) / spot * 100
        spot_pnl_per_100 = (ns - spot) * 100

        # --- L2: 0.70Δ 1DTE call (current production) ---
        call_pnl = None
        cand = bar_e[(bar_e["expiry"] == target_exp) &
                     (bar_e["right"] == "C") &
                     (bar_e["bid"] > 0) & (bar_e["ask"] > 0) &
                     (bar_e["delta"].abs() > 0.05)]
        if not cand.empty:
            r = cand.assign(dd=(cand["delta"].abs() - 0.70).abs()).sort_values("dd").iloc[0]
            f = fill.simulate_entry(float(r["bid"]), float(r["ask"]), "BUY",
                                    datetime.combine(d, datetime.min.time()).replace(hour=13))
            if f.filled:
                K = float(r["strike"])
                call_pnl = (max(ns - K, 0) - f.fill_price) * 100

        # --- L3: ATM call spread (long ATM, short ATM+$5) ---
        spread_pnl = None
        calls_today = bar_e[(bar_e["expiry"] == target_exp) &
                            (bar_e["right"] == "C") &
                            (bar_e["bid"] > 0) & (bar_e["ask"] > 0)]
        if not calls_today.empty:
            # Long leg: ATM (closest to spot)
            long_row = calls_today.iloc[(calls_today["strike"] - spot).abs().argmin()]
            K_long = float(long_row["strike"])
            # Short leg: ATM + $5
            short_candidates = calls_today[calls_today["strike"] >= K_long + 4.5]
            if not short_candidates.empty:
                short_row = short_candidates.iloc[(short_candidates["strike"] - (K_long + 5)).abs().argmin()]
                K_short = float(short_row["strike"])
                # Buy long, sell short
                buy_fill = fill.simulate_entry(float(long_row["bid"]), float(long_row["ask"]),
                                               "BUY", datetime.combine(d, datetime.min.time()).replace(hour=13))
                # Sell short leg at bid + 25% of spread (conservative)
                short_bid = float(short_row["bid"])
                short_ask = float(short_row["ask"])
                sell_px = short_bid + 0.25 * (short_ask - short_bid)
                if buy_fill.filled and short_bid > 0:
                    net_debit = buy_fill.fill_price - sell_px
                    payoff = max(ns - K_long, 0) - max(ns - K_short, 0)
                    spread_pnl = (payoff - net_debit) * 100

        trades.append({
            "d": d, "bucket": bucket(d),
            "spot_ret_pct": spot_ret_pct,
            "spot_pnl_per_100": spot_pnl_per_100,
            "call_pnl": call_pnl,
            "spread_pnl": spread_pnl,
        })

    df = pd.DataFrame(trades)
    print(f"Total v5 signals fired: {len(df)}")
    print()

    def summary(lbl, s, col):
        vals = s[col].dropna()
        if vals.empty:
            return f"{lbl:14s} {col:20s} empty"
        w = (vals > 0).sum()
        pfd = -vals[vals < 0].sum()
        pf = vals[vals > 0].sum() / pfd if pfd > 0 else float("inf")
        mean = vals.mean()
        total = vals.sum()
        sh = mean / vals.std() * np.sqrt(252) if vals.std() > 0 else 0
        return (f"{lbl:10s} | N={len(vals):3d} WR={w/len(vals)*100:5.1f}% "
                f"mean={mean:+7.2f} total={total:+8.0f} PF={pf:.2f} Sh={sh:.2f}")

    for layer, col in [
        ("L1 SPOT (100sh)", "spot_pnl_per_100"),
        ("L2 0.70Δ CALL", "call_pnl"),
        ("L3 CALL SPREAD", "spread_pnl"),
    ]:
        print(f"=== {layer} ===")
        for b in ["Y2023", "EXT_OOS", "ORIG_OOS", "ORIG_IS", "ALL"]:
            sub = df if b == "ALL" else df[df["bucket"] == b]
            print(summary(b, sub, col))
        print()

    # KEY DIAGNOSTIC: if L1 has no edge but L2 loses → instrument problem
    # If L1 has no edge AND L2 loses → signal problem
    # If L1 has edge AND L2 loses → theta/IV drag → try L3 (spread)
    print("=== DIAGNOSTIC ===")
    all_spot = df["spot_pnl_per_100"].dropna()
    all_call = df["call_pnl"].dropna()
    all_spread = df["spread_pnl"].dropna()
    print(f"SPOT  mean per-100: {all_spot.mean():+.2f}  (H0: mean=0,  t-stat={all_spot.mean()/(all_spot.std()/np.sqrt(len(all_spot))):.2f})")
    print(f"CALL  mean per-contract: {all_call.mean():+.2f}")
    print(f"SPREAD mean per-contract: {all_spread.mean():+.2f}")

    if all_spot.mean() > 0 and all_call.mean() < 0:
        print("\n>>> INSTRUMENT PROBLEM: spot has edge, call loses to theta/IV drag. Try spread.")
    elif all_spot.mean() <= 0:
        print("\n>>> SIGNAL PROBLEM: signal does not predict even spot direction. Kill project.")
    else:
        print("\n>>> Signal works on all 3 instruments.")


if __name__ == "__main__":
    main()
