"""Regime-switching combo: short straddle in low-vol, v5 long-call in high-vol.

Theory: short-premium strategies profit when realized vol < implied (quiet
trends, mean reversion around a level). Long-premium strategies profit when
realized vol > implied (fat tails, big moves). If we can classify the current
regime using trailing IV, we should pick the right structure.

Uses 20-day rolling median of ATM IV as regime classifier:
  - Below regime_threshold → low-vol → sell ATM straddle
  - Above regime_threshold → high-vol → v5 gex signal (buy 0.70Δ call if fires)
  - threshold = ROLLING 60-day median of IV (walk-forward, no lookahead)
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

    # Pre-scan: collect per-day spot and ATM IV (walk-forward features)
    daily = []
    for fp in files:
        try:
            d = datetime.strptime(fp.stem, "%Y%m%d").date()
        except ValueError: continue
        bar = pd.read_parquet(fp)
        if bar.empty or "spot" not in bar.columns: continue
        spot = float(bar["spot"].dropna().iloc[0])
        # ATM call IV at nearest expiry
        exps = sorted(bar["expiry"].unique())
        if not exps: continue
        near_exp = exps[0]
        near = bar[(bar["expiry"] == near_exp) & (bar["right"] == "C") & (bar["iv"] > 0)]
        if near.empty: continue
        atm = near.iloc[(near["strike"] - spot).abs().argmin()]
        daily.append({"d": d, "spot": spot, "atm_iv": float(atm["iv"])})

    daily_df = pd.DataFrame(daily).sort_values("d").reset_index(drop=True)
    # Rolling 60-day median IV, shifted by 1 to avoid lookahead
    daily_df["iv_median_60"] = daily_df["atm_iv"].rolling(60).median().shift(1)
    daily_df["regime"] = np.where(
        daily_df["atm_iv"] < daily_df["iv_median_60"], "low_vol", "high_vol"
    )
    daily_df.loc[daily_df["iv_median_60"].isna(), "regime"] = "warmup"

    trades = []
    for i, fp in enumerate(files[:-1]):
        try:
            d = datetime.strptime(fp.stem, "%Y%m%d").date()
            d_next = datetime.strptime(files[i+1].stem, "%Y%m%d").date()
        except ValueError: continue
        dr = daily_df[daily_df["d"] == d]
        if dr.empty: continue
        regime = dr.iloc[0]["regime"]
        if regime == "warmup": continue

        bar = pd.read_parquet(fp)
        if bar.empty: continue
        spot = float(bar["spot"].dropna().iloc[0])
        target_exp = d_next.strftime("%Y%m%d")

        next_bar = pd.read_parquet(files[i+1])
        ns = float(next_bar["spot"].dropna().iloc[0]) if "spot" in next_bar.columns else spot

        if regime == "low_vol":
            # Sell ATM straddle
            chain = bar[(bar["expiry"] == target_exp) & (bar["bid"] > 0) & (bar["ask"] > 0)]
            calls = chain[chain["right"] == "C"]
            puts = chain[chain["right"] == "P"]
            if calls.empty or puts.empty: continue
            call_row = calls.iloc[(calls["strike"] - spot).abs().argmin()]
            put_row = puts.iloc[(puts["strike"] - spot).abs().argmin()]
            if abs(call_row["strike"] - put_row["strike"]) > 2: continue
            def sell_px(row):
                b, a = float(row["bid"]), float(row["ask"])
                return (a + b) / 2 - 0.25 * (a - b)
            c_sell = sell_px(call_row); p_sell = sell_px(put_row)
            c_intr = max(ns - float(call_row["strike"]), 0)
            p_intr = max(float(put_row["strike"]) - ns, 0)
            pnl = ((c_sell + p_sell) - (c_intr + p_intr)) * 100
            trades.append({"d": d, "bucket": bucket(d), "regime": regime,
                           "strategy": "short_straddle", "pnl": pnl})

        elif regime == "high_vol":
            # v5 signal: NEG_GAMMA + pos<0.15
            bar_enriched = enrich_greeks(bar, spot, as_of=d)
            gex = calculate_gex_profile(bar_enriched, spot)
            lv = identify_levels(gex, spot)
            if not lv.call_wall or not lv.put_wall or lv.call_wall <= lv.put_wall:
                continue
            pos = (spot - lv.put_wall) / (lv.call_wall - lv.put_wall)
            if lv.regime != "NEGATIVE_GAMMA" or pos >= 0.15:
                continue
            # Buy 0.70Δ 1DTE call
            cand = bar_enriched[(bar_enriched["expiry"] == target_exp) &
                                (bar_enriched["right"] == "C") &
                                (bar_enriched["bid"] > 0) & (bar_enriched["ask"] > 0) &
                                (bar_enriched["delta"].abs() > 0.05)]
            if cand.empty: continue
            r = cand.assign(dd=(cand["delta"].abs() - 0.70).abs()).sort_values("dd").iloc[0]
            f = fill.simulate_entry(float(r["bid"]), float(r["ask"]), "BUY",
                                    datetime.combine(d, datetime.min.time()).replace(hour=13))
            if not f.filled: continue
            K = float(r["strike"])
            pnl = (max(ns - K, 0) - f.fill_price) * 100
            trades.append({"d": d, "bucket": bucket(d), "regime": regime,
                           "strategy": "v5_long_call", "pnl": pnl})

    df = pd.DataFrame(trades)
    print(f"Total trades: {len(df)}  (short_straddle: {(df['strategy']=='short_straddle').sum()}, v5_long_call: {(df['strategy']=='v5_long_call').sum()})")

    def summary(lbl, s):
        if s.empty: return f"{lbl} empty"
        w = (s["pnl"] > 0).sum()
        pfd = -s[s["pnl"] < 0]["pnl"].sum()
        pf = s[s["pnl"] > 0]["pnl"].sum() / pfd if pfd > 0 else float("inf")
        cum = s["pnl"].cumsum().values
        peak = np.maximum.accumulate(cum)
        dd = (cum - peak).min()
        sh = s["pnl"].mean() / s["pnl"].std() * np.sqrt(252) if s["pnl"].std() > 0 else 0
        return (f"{lbl:14s} N={len(s):3d} WR={w/len(s)*100:5.1f}% "
                f"PnL=${s['pnl'].sum():+.0f} PF={pf:.2f} DD=${dd:+.0f} Sh={sh:.2f}")

    print("\n=== Regime-switch combined — by bucket ===")
    for b in ["Y2023", "EXT_OOS", "ORIG_OOS", "ORIG_IS", "ALL"]:
        sub = df if b == "ALL" else df[df["bucket"] == b]
        print(summary(b, sub))

    print("\n=== Breakdown by strategy used ===")
    for s_name in ["short_straddle", "v5_long_call"]:
        for b in ["Y2023", "EXT_OOS", "ORIG_OOS", "ORIG_IS", "ALL"]:
            sub = df[df["strategy"] == s_name] if b == "ALL" else df[(df["strategy"] == s_name) & (df["bucket"] == b)]
            print(summary(f"{s_name}/{b[:8]}", sub))
        print()


if __name__ == "__main__":
    main()
