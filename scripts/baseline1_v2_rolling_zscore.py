"""Baseline 1 v2: Fixes applied.

Fix 1: Close-to-close spot definition.
  OLD: median(underlying_price) across day D's 1-min Greeks bars
  NEW: last available underlying_price before 4:00 PM ET (15:59) per day

Fix 2: Rolling z-score (walk-forward) instead of yearly in-sample.
  OLD: z = (x - year.mean()) / year.std()   # includes future info in year
  NEW: z = (x - rolling_60d.mean()) / rolling_60d.std()  shifted by 1 (no same-day)

These two fixes are independent:
  - Fix 1 addresses spot measurement accuracy
  - Fix 2 addresses z-score leakage (using same-day value in its own normalizer)

Run: python scripts/baseline1_v2_rolling_zscore.py
"""
from __future__ import annotations
import logging
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import glob

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("baseline1_v2")

DATA_DIR = Path("/Users/ethanyang/0dte-strategy/data/historical_0dte")
OLD_FLOW = Path("/Users/ethanyang/0dte-strategy/data/baseline1_signed_flow.parquet")
OUT_PARQUET = Path("/Users/ethanyang/0dte-strategy/data/baseline1_v2.parquet")
REPORT = Path("/Users/ethanyang/0dte-strategy/logs/baseline1_v2_report.md")


def compute_close_spot(day_dir: Path) -> tuple[date, float]:
    """Get last underlying_price (closest to 15:59 ET) from greeks parquets.

    Returns (date, close_spot). Returns (date, nan) if no valid price found.
    """
    d = datetime.strptime(day_dir.name.split("=")[1], "%Y-%m-%d").date()
    files = sorted((day_dir / "greeks").glob("*.parquet"))
    if not files:
        return d, np.nan

    # Try last-minute strikes near money (most active, likely to have non-zero UP)
    # Just check ALL files' last rows, take latest non-zero underlying_price
    last_prices = []
    for f in files:
        try:
            df = pd.read_parquet(f, columns=["timestamp", "underlying_price"])
            df = df[df["underlying_price"] > 0]
            if df.empty:
                continue
            # Sort by timestamp, take last
            df = df.sort_values("timestamp")
            last_prices.append((df["timestamp"].iloc[-1], df["underlying_price"].iloc[-1]))
        except Exception:
            continue

    if not last_prices:
        return d, np.nan

    # Return the underlying_price with latest timestamp (close-to-close)
    last_prices.sort()
    return d, float(last_prices[-1][1])


def main():
    logger.info("Loading old baseline1 signal data...")
    df = pd.read_parquet(OLD_FLOW)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    logger.info(f"Loaded {len(df)} days with signed flow")

    # === Fix 1: Compute proper close spot ===
    logger.info("Computing close-to-close spot from last-bar underlying_price...")
    close_spots = {}
    day_dirs = sorted(DATA_DIR.glob("date=*"))
    for i, dd in enumerate(day_dirs):
        d, sp = compute_close_spot(dd)
        close_spots[pd.Timestamp(d)] = sp
        if (i + 1) % 100 == 0:
            logger.info(f"  {i+1}/{len(day_dirs)}")

    df["close_spot"] = df["date"].map(close_spots)
    df = df.dropna(subset=["close_spot"]).copy()
    logger.info(f"Close spots filled for {len(df)} days")

    # Next-day close return (true close-to-close)
    df["next_close_spot"] = df["close_spot"].shift(-1)
    df["next_day_ret_pct_true"] = (df["next_close_spot"] - df["close_spot"]) / df["close_spot"] * 100
    df = df.dropna(subset=["next_day_ret_pct_true"])

    # === Fix 2: Rolling z-score (walk-forward, no lookahead) ===
    ROLL = 60  # trailing window days
    for col in ["signed_net_vol", "signed_net_premium"]:
        df[f"{col}_roll_mean"] = df[col].rolling(ROLL, min_periods=30).mean().shift(1)
        df[f"{col}_roll_std"] = df[col].rolling(ROLL, min_periods=30).std().shift(1)
        df[f"{col}_zroll"] = (df[col] - df[f"{col}_roll_mean"]) / df[f"{col}_roll_std"]

    # Only evaluate on days where we have enough history
    df = df.dropna(subset=["signed_net_vol_zroll"]).copy()
    logger.info(f"After rolling warmup: {len(df)} evaluation days")

    # Build signals at threshold
    THRESHOLD = 0.5
    df["signal_vol_v2"] = np.where(
        df["signed_net_vol_zroll"] >= THRESHOLD, 1,
        np.where(df["signed_net_vol_zroll"] <= -THRESHOLD, -1, 0)
    )
    df["signal_prem_v2"] = np.where(
        df["signed_net_premium_zroll"] >= THRESHOLD, 1,
        np.where(df["signed_net_premium_zroll"] <= -THRESHOLD, -1, 0)
    )

    df["trade_return_vol_v2"] = df["signal_vol_v2"] * df["next_day_ret_pct_true"]
    df["trade_return_prem_v2"] = df["signal_prem_v2"] * df["next_day_ret_pct_true"]

    df["pred_vol_v2"] = np.sign(df["signed_net_vol_zroll"])
    df["actual_direction_true"] = np.sign(df["next_day_ret_pct_true"])

    df.to_parquet(OUT_PARQUET, compression="zstd")
    logger.info(f"Saved: {OUT_PARQUET}")

    def metrics(subset: pd.DataFrame, ret_col: str, sig_col: str) -> dict:
        trades = subset[subset[sig_col] != 0]
        if trades.empty:
            return {"n": 0, "wr": 0, "mean": 0, "total": 0, "sharpe": 0, "pf": 0}
        rets = trades[ret_col]
        wins = (rets > 0).sum()
        pf_den = -rets[rets < 0].sum()
        pf = rets[rets > 0].sum() / pf_den if pf_den > 0 else float("inf")
        sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
        return {
            "n": len(rets), "wr": wins/len(rets)*100,
            "mean": rets.mean(), "total": rets.sum(),
            "sharpe": sharpe, "pf": pf,
        }

    # Comparison: v1 (in-sample yearly z-score) vs v2 (rolling 60-day walk-forward)
    # Use old metric col from df (loaded parquet has old signal_vol + trade_return_vol)
    out = []
    out.append(f"# Baseline 1 v2 — Rolling Z-score + True Close-to-Close\n")
    out.append(f"Generated: {datetime.now().isoformat()}")
    out.append(f"Evaluation days (after 60d warmup): {len(df)}")
    out.append(f"Threshold: |z| >= {THRESHOLD}")
    out.append(f"Rolling window: {ROLL} days, shifted by 1 (strict walk-forward)")
    out.append("")

    out.append("## 1. v1 vs v2 Comparison (Vol-signed)")
    out.append("| Version | Signal Spec | Return Spec | N | WR | Mean | Sharpe | PF |")
    out.append("|---------|-------------|-------------|---|-----|------|--------|-----|")

    # v1: original columns from loaded parquet
    m_v1 = metrics(df, "trade_return_vol", "signal_vol")
    out.append(f"| v1 (in-sample z) | year z-score | median-spot return | {m_v1['n']} | {m_v1['wr']:.1f}% | {m_v1['mean']:+.3f}% | {m_v1['sharpe']:.2f} | {m_v1['pf']:.2f} |")

    # v1.5: v1 signal but true close return
    df["trade_return_vol_v15"] = df["signal_vol"] * df["next_day_ret_pct_true"]
    m_v15 = metrics(df, "trade_return_vol_v15", "signal_vol")
    out.append(f"| v1.5 | year z-score | **true close** | {m_v15['n']} | {m_v15['wr']:.1f}% | {m_v15['mean']:+.3f}% | {m_v15['sharpe']:.2f} | {m_v15['pf']:.2f} |")

    # v2: rolling signal + true close
    m_v2 = metrics(df, "trade_return_vol_v2", "signal_vol_v2")
    out.append(f"| v2 (walk-fwd) | **rolling {ROLL}d z** | **true close** | {m_v2['n']} | {m_v2['wr']:.1f}% | {m_v2['mean']:+.3f}% | {m_v2['sharpe']:.2f} | {m_v2['pf']:.2f} |")
    out.append("")

    # Direction accuracy
    acc_v1 = (np.sign(df["signed_net_vol_zyr"]) == df["actual_direction_true"]).sum() / len(df) * 100
    acc_v2 = (df["pred_vol_v2"] == df["actual_direction_true"]).sum() / len(df) * 100
    out.append("## 2. Direction Prediction Accuracy")
    out.append(f"- v1 (year z-score) predictions: **{acc_v1:.1f}%** correct ({len(df)} days)")
    out.append(f"- v2 (rolling z-score) predictions: **{acc_v2:.1f}%** correct")
    out.append(f"- Coin flip: 50%")
    out.append("")

    # Signal distribution
    out.append("## 3. Signal Distribution v2")
    sv = df["signal_vol_v2"].value_counts().to_dict()
    out.append(f"- Long: {sv.get(1, 0)}, Short: {sv.get(-1, 0)}, No signal: {sv.get(0, 0)}")
    out.append("")

    # By year v2
    out.append("## 4. By Year (v2 — rolling z, true close)")
    out.append("| Year | N | WR | Mean | Sharpe | PF |")
    out.append("|------|---|-----|------|--------|-----|")
    df["year"] = df["date"].dt.year
    for y, sub in df.groupby("year"):
        m = metrics(sub, "trade_return_vol_v2", "signal_vol_v2")
        out.append(f"| {y} | {m['n']} | {m['wr']:.1f}% | {m['mean']:+.3f}% | {m['sharpe']:.2f} | {m['pf']:.2f} |")
    out.append("")

    # Unconditional
    uncond_ret = df["next_day_ret_pct_true"]
    uncond_sharpe = uncond_ret.mean() / uncond_ret.std() * np.sqrt(252)
    uncond_wr = (uncond_ret > 0).sum() / len(uncond_ret) * 100
    out.append("## 5. Unconditional Baseline (true close-to-close)")
    out.append(f"- Mean: **{uncond_ret.mean():+.3f}%**")
    out.append(f"- WR: **{uncond_wr:.1f}%**")
    out.append(f"- Sharpe: **{uncond_sharpe:.2f}**")
    out.append("")

    # Verdict
    out.append("## 6. Verdict")
    edge_v1 = m_v1["sharpe"] - uncond_sharpe
    edge_v2 = m_v2["sharpe"] - uncond_sharpe
    out.append(f"- v1 excess Sharpe over unconditional: **{edge_v1:+.2f}**")
    out.append(f"- v2 excess Sharpe over unconditional: **{edge_v2:+.2f}**")
    out.append("")
    if m_v2["sharpe"] < uncond_sharpe + 0.3:
        out.append("**VERDICT**: After walk-forward + true close, edge collapses to noise. Bulk of v1 Sharpe was in-sample z-score leakage.")
    elif m_v2["sharpe"] > uncond_sharpe + 0.8:
        out.append("**VERDICT**: Edge survives walk-forward. Proceed to block bootstrap + friction modeling.")
    else:
        out.append("**VERDICT**: Marginal edge. Need block bootstrap CI to determine if statistically significant.")

    REPORT.write_text("\n".join(out))
    logger.info(f"Report: {REPORT}")
    print("\n".join(out))


if __name__ == "__main__":
    main()
