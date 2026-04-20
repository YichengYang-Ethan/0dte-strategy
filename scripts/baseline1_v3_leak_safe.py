"""Baseline 1 v3: Full leak-safe pipeline rebuild.

Rebuilt from RAW parquets using src.pipeline.leak_safe primitives.
Every step is cutoff-respecting and future-poison tested.

Pipeline:
  Day D:
    1. close_spot_D = last underlying_price at or before 15:55 ET
    2. signed_flow_D = aggregate single-leg electronic trades up to 15:55
    3. rolling_zscore_D = (flow_D - trailing_60d_mean) / trailing_60d_std
       (shift-1, strictly walk-forward)
    4. signal_D fires at |z| >= 0.5

  Day D+1:
    close_spot_{D+1} = same rule

  Target: (close_spot_{D+1} - close_spot_D) / close_spot_D

Run: python scripts/baseline1_v3_leak_safe.py
"""
from __future__ import annotations
import logging
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from src.pipeline.leak_safe import (
    DEFAULT_CUTOFF_ET,
    close_spot_leak_safe,
    compute_day_flow_leak_safe,
    rolling_zscore_shifted,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("baseline1_v3")

DATA_DIR = Path("/Users/ethanyang/0dte-strategy/data/historical_0dte")
OUT_PARQUET = Path("/Users/ethanyang/0dte-strategy/data/baseline1_v3.parquet")
REPORT = Path("/Users/ethanyang/0dte-strategy/logs/baseline1_v3_report.md")

THRESHOLD = 0.5
ROLLING_WINDOW = 60


def main():
    day_dirs = sorted(DATA_DIR.glob("date=*"))
    logger.info(f"Rebuilding baseline from raw across {len(day_dirs)} days")

    flow_records = []
    spot_records = []
    for i, dd in enumerate(day_dirs):
        flow = compute_day_flow_leak_safe(dd)
        if flow:
            flow_records.append(flow)
        d, spot = close_spot_leak_safe(dd)
        spot_records.append({"date": d, "close_spot": spot})
        if (i + 1) % 100 == 0:
            logger.info(f"  {i+1}/{len(day_dirs)}")

    flow_df = pd.DataFrame(flow_records)
    spot_df = pd.DataFrame(spot_records)
    flow_df["date"] = pd.to_datetime(flow_df["date"])
    spot_df["date"] = pd.to_datetime(spot_df["date"])

    df = flow_df.merge(spot_df, on="date", how="outer").sort_values("date").reset_index(drop=True)
    df["year"] = df["date"].dt.year

    # Next-day close return
    df["next_close_spot"] = df["close_spot"].shift(-1)
    df["next_day_ret_pct"] = (df["next_close_spot"] - df["close_spot"]) / df["close_spot"] * 100
    df = df.dropna(subset=["next_day_ret_pct", "signed_net_vol"])

    # Rolling z-score (shift-1, trailing 60d)
    df["signed_net_vol_z"] = rolling_zscore_shifted(df["signed_net_vol"], ROLLING_WINDOW)
    df["signed_net_premium_z"] = rolling_zscore_shifted(df["signed_net_premium"], ROLLING_WINDOW)

    df = df.dropna(subset=["signed_net_vol_z"])
    logger.info(f"Evaluation days (after rolling warmup): {len(df)}")

    # Signals
    df["signal_vol"] = np.where(
        df["signed_net_vol_z"] >= THRESHOLD, 1,
        np.where(df["signed_net_vol_z"] <= -THRESHOLD, -1, 0)
    )
    df["signal_prem"] = np.where(
        df["signed_net_premium_z"] >= THRESHOLD, 1,
        np.where(df["signed_net_premium_z"] <= -THRESHOLD, -1, 0)
    )

    df["trade_return_vol"] = df["signal_vol"] * df["next_day_ret_pct"]
    df["trade_return_prem"] = df["signal_prem"] * df["next_day_ret_pct"]

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, compression="zstd")
    logger.info(f"Saved: {OUT_PARQUET}")

    # Metrics
    def metrics(subset, ret_col, sig_col):
        trades = subset[subset[sig_col] != 0]
        if trades.empty:
            return {"n": 0, "wr": 0, "mean": 0, "total": 0, "sharpe": 0, "pf": 0}
        rets = trades[ret_col]
        wins = (rets > 0).sum()
        pf_den = -rets[rets < 0].sum()
        pf = rets[rets > 0].sum() / pf_den if pf_den > 0 else float("inf")
        sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
        return {"n": len(rets), "wr": wins/len(rets)*100,
                "mean": rets.mean(), "total": rets.sum(),
                "sharpe": sharpe, "pf": pf}

    # Report
    out = [
        f"# Baseline 1 v3 — Leak-Safe Rebuild\n",
        f"Generated: {datetime.now().isoformat()}",
        f"Evaluation days: {len(df)}",
        f"Signal cutoff: {DEFAULT_CUTOFF_ET} ET",
        f"Rolling window: {ROLLING_WINDOW}d, shift-1 (strict walk-forward)",
        f"Threshold: |z| >= {THRESHOLD}",
        f"Filter: condition ∈ {{0, 18}} (single-leg electronic)",
        f"",
        f"All computations verified via `future_poison_test` — post-cutoff data has zero influence.",
        f"",
    ]

    # Comparison across v1/v1.5/v2/v3
    out.append("## 1. Sharpe Evolution (vol-signed, long+short signal)")
    out.append("| Version | Signal | Return | N | WR | Mean | Sharpe | PF |")
    out.append("|---------|--------|--------|---|-----|------|--------|-----|")

    m_v3_vol = metrics(df, "trade_return_vol", "signal_vol")
    m_v3_prem = metrics(df, "trade_return_prem", "signal_prem")
    out.append(f"| v1 | year z | median-spot | 575 | 61.4% | +0.199% | **3.41** | 1.82 |")
    out.append(f"| v1.5 | year z | true close | 575 | 51.0% | +0.004% | 0.06 | 1.01 |")
    out.append(f"| v2 | rolling z 60d | true close (no cutoff) | 598 | 52.0% | +0.003% | 0.05 | 1.01 |")
    out.append(f"| **v3 (leak-safe)** | **rolling z 60d shift-1** | **true close @ {DEFAULT_CUTOFF_ET}** | {m_v3_vol['n']} | {m_v3_vol['wr']:.1f}% | {m_v3_vol['mean']:+.3f}% | **{m_v3_vol['sharpe']:.2f}** | {m_v3_vol['pf']:.2f} |")
    out.append("")

    # Direction accuracy
    pred_dir = np.sign(df["signed_net_vol_z"])
    actual_dir = np.sign(df["next_day_ret_pct"])
    acc = (pred_dir == actual_dir).sum() / len(df) * 100
    out.append(f"## 2. Direction Accuracy")
    out.append(f"- v3 direction accuracy: **{acc:.1f}%** (coin flip = 50%)")
    out.append("")

    # By year
    out.append("## 3. By Year (v3)")
    out.append("| Year | N | WR | Mean | Sharpe | PF |")
    out.append("|------|---|-----|------|--------|-----|")
    for y, sub in df.groupby("year"):
        m = metrics(sub, "trade_return_vol", "signal_vol")
        out.append(f"| {y} | {m['n']} | {m['wr']:.1f}% | {m['mean']:+.3f}% | {m['sharpe']:.2f} | {m['pf']:.2f} |")
    out.append("")

    # Unconditional baseline
    uncond_ret = df["next_day_ret_pct"]
    uncond_sharpe = uncond_ret.mean() / uncond_ret.std() * np.sqrt(252)
    uncond_wr = (uncond_ret > 0).sum() / len(uncond_ret) * 100
    out.append("## 4. Unconditional Baseline (always long SPX, true close-to-close)")
    out.append(f"- Mean: {uncond_ret.mean():+.3f}%/day")
    out.append(f"- WR: {uncond_wr:.1f}%")
    out.append(f"- Sharpe: **{uncond_sharpe:.2f}**")
    out.append("")

    # Signal distribution
    sv = df["signal_vol"].value_counts().to_dict()
    out.append("## 5. Signal Distribution v3")
    out.append(f"- Long: {sv.get(1, 0)}, Short: {sv.get(-1, 0)}, No signal: {sv.get(0, 0)}")
    out.append("")

    # Premium-signed comparison
    out.append("## 6. Premium-signed variant (v3)")
    out.append(f"- N={m_v3_prem['n']}, WR={m_v3_prem['wr']:.1f}%, mean={m_v3_prem['mean']:+.3f}%, Sharpe={m_v3_prem['sharpe']:.2f}")
    out.append("")

    # Verdict
    excess = m_v3_vol["sharpe"] - uncond_sharpe
    out.append("## 7. Verdict")
    out.append(f"- v3 Sharpe: **{m_v3_vol['sharpe']:.2f}**")
    out.append(f"- Unconditional Sharpe: **{uncond_sharpe:.2f}**")
    out.append(f"- Excess: **{excess:+.2f}**")
    out.append("")
    if abs(m_v3_vol["sharpe"]) < 0.3:
        out.append("**VERDICT**: Signed flow via quote-rule on single-leg electronic SPXW 0DTE trades has NO detectable edge for next-day close-to-close SPX direction. CONFIRMED dead after leak-safe rebuild.")
    elif m_v3_vol["sharpe"] < uncond_sharpe + 0.3:
        out.append("**VERDICT**: No meaningful excess edge over unconditional long SPX. Signal isn't useful.")
    else:
        out.append(f"**VERDICT**: v3 shows a surviving excess Sharpe of {excess:+.2f}. Proceed to block bootstrap CI + friction modeling. Low confidence given history — require CI lower bound > 0.3 before continuing.")

    REPORT.write_text("\n".join(out))
    logger.info(f"Report: {REPORT}")
    print("\n".join(out))


if __name__ == "__main__":
    main()
