"""Day 2: Extract 4 feature families across 952 days × 2 decision times.

Features (all as-of t, 15m and 30m windows for F1/F2):
  F1: delta/gamma-weighted signed flow (call/put/net)
  F2: cross-strike concentration (HHI, top1, top3)
  F3: slow state — ATM ±1% OI×gamma per side (calls vs puts)
  F4: interaction (state × concentration × flow_direction)

Output: data/intraday_features.parquet
"""
from __future__ import annotations
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from src.pipeline.intraday_features import compute_features_one_day

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("day2")

DATA_DIR = Path("/Users/ethanyang/0dte-strategy/data/historical_0dte")
OUT_PARQUET = Path("/Users/ethanyang/0dte-strategy/data/intraday_features.parquet")
REPORT = Path("/Users/ethanyang/0dte-strategy/logs/intraday_day2_report.md")


def main():
    day_dirs = sorted(DATA_DIR.glob("date=*"))
    logger.info(f"Computing intraday features for {len(day_dirs)} days × 2 decision times...")

    records = []
    for i, dd in enumerate(day_dirs):
        for t in ["15:00", "14:30"]:
            try:
                rec = compute_features_one_day(dd, t_hhmm=t)
                if rec:
                    records.append(rec)
            except Exception as e:
                logger.warning(f"{dd.name} @ {t}: {e}")
        if (i + 1) % 50 == 0:
            logger.info(f"  {i+1}/{len(day_dirs)}")

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, compression="zstd")
    logger.info(f"Saved: {OUT_PARQUET} ({len(df)} rows, {len(df.columns)} cols)")

    # Report
    out = [
        "# Day 2 Intraday Features — MVP Plan\n",
        f"Generated: {datetime.now().isoformat()}",
        f"Days × decision times: {len(df)}",
        f"Features extracted: {len(df.columns) - 3}",
        "",
        "## Feature columns",
        "| Family | Columns |",
        "|--------|---------|",
        f"| F1 flow (×15m,30m) | flow_delta_call, flow_delta_put, flow_delta_net, flow_gamma_call, flow_gamma_put, flow_gamma_net, n_trades |",
        f"| F2 concentration | hhi, top1_share, top3_share, n_strikes |",
        f"| F3 slow state | atm_call_gex, atm_put_gex, atm_gex_skew, atm_gex_total, spot_t |",
        f"| F4 interaction | interaction_sign, interaction_weighted |",
        "",
    ]

    prim = df[df["decision_time"] == "15:00"]
    out.append("## Primary (t=15:00) feature distribution")
    summary_cols = [
        "flow_delta_net_30m",
        "flow_gamma_net_30m",
        "hhi_30m",
        "top1_share_30m",
        "top3_share_30m",
        "atm_gex_skew",
        "interaction_sign",
        "interaction_weighted",
    ]
    for col in summary_cols:
        if col in prim.columns:
            s = prim[col].describe().round(6)
            out.append(f"- **{col}**: mean={s['mean']:.4g}, std={s['std']:.4g}, min={s['min']:.4g}, max={s['max']:.4g}")
    out.append("")

    # Coverage
    out.append("## Coverage")
    out.append(f"- Days processed: {df['date'].nunique()}")
    out.append(f"- Rows for t=15:00: {len(prim)}")
    out.append(f"- Rows for t=14:30: {len(df[df['decision_time'] == '14:30'])}")
    out.append(f"- Missing F1 flow_delta_net_30m: {prim['flow_delta_net_30m'].isna().sum()}")
    out.append(f"- Missing F2 hhi_30m: {prim['hhi_30m'].isna().sum() if 'hhi_30m' in prim.columns else 'N/A'}")
    out.append(f"- Missing F3 atm_gex_skew: {prim['atm_gex_skew'].isna().sum() if 'atm_gex_skew' in prim.columns else 'N/A'}")
    out.append("")

    # Sample rows
    out.append("## Sample (first 3 days, t=15:00)")
    cols_show = ["date", "spot_t", "flow_delta_net_30m", "top3_share_30m", "atm_gex_skew", "interaction_sign"]
    cols_show = [c for c in cols_show if c in prim.columns]
    out.append(prim[cols_show].head(3).to_markdown(index=False))
    out.append("")

    REPORT.write_text("\n".join(out))
    logger.info(f"Report: {REPORT}")


if __name__ == "__main__":
    main()
