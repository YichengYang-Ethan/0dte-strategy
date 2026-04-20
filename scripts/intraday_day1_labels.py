"""Day 1 of GPT Pro intraday MVP plan: Fixed-time intraday labels.

Decision times:
  - Primary: 15:00 ET
  - Robustness: 14:30 ET

Labels (all from decision_time t → 15:55 ET):
  - signed_ret_pct: (spot_end − spot_t) / spot_t × 100
  - abs_ret_pct: |signed_ret_pct|
  - realized_var: sum of squared 1-min log returns in [t, 15:55]

NO next-day labels. All targets are INTRADAY.

Output: data/intraday_labels.parquet
"""
from __future__ import annotations
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from src.pipeline.leak_safe import (
    intraday_labels_leak_safe,
    future_poison_test,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("day1")

DATA_DIR = Path("/Users/ethanyang/0dte-strategy/data/historical_0dte")
OUT_PARQUET = Path("/Users/ethanyang/0dte-strategy/data/intraday_labels.parquet")
REPORT = Path("/Users/ethanyang/0dte-strategy/logs/intraday_day1_report.md")


def main():
    day_dirs = sorted(DATA_DIR.glob("date=*"))
    logger.info(f"Computing intraday labels for {len(day_dirs)} days...")

    records = []
    for i, dd in enumerate(day_dirs):
        # Primary t=15:00
        r_primary = intraday_labels_leak_safe(dd, decision_time="15:00")
        # Robustness t=14:30
        r_robust = intraday_labels_leak_safe(dd, decision_time="14:30")

        if r_primary:
            records.append({
                "date": r_primary["date"],
                "decision_time": "15:00",
                "spot_t": r_primary["spot_t"],
                "spot_end": r_primary["spot_end"],
                "n_bars": r_primary["n_bars"],
                "signed_ret_pct": r_primary["signed_ret_pct"],
                "abs_ret_pct": r_primary["abs_ret_pct"],
                "realized_var": r_primary["realized_var"],
            })
        if r_robust:
            records.append({
                "date": r_robust["date"],
                "decision_time": "14:30",
                "spot_t": r_robust["spot_t"],
                "spot_end": r_robust["spot_end"],
                "n_bars": r_robust["n_bars"],
                "signed_ret_pct": r_robust["signed_ret_pct"],
                "abs_ret_pct": r_robust["abs_ret_pct"],
                "realized_var": r_robust["realized_var"],
            })

        if (i + 1) % 100 == 0:
            logger.info(f"  {i+1}/{len(day_dirs)}")

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, compression="zstd")
    logger.info(f"Saved: {OUT_PARQUET} ({len(df)} rows)")

    # === Verify leak-safety: future-poison on 3 random days ===
    logger.info("Verifying leak-safety via future-poison test on 3 random days...")
    rng = np.random.default_rng(7)
    sample = rng.choice(day_dirs, 3, replace=False).tolist()
    poison_results = []
    for dd in sample:
        for t in ["15:00", "14:30"]:
            def computation(p, c):
                return intraday_labels_leak_safe(p, decision_time=t)
            passed, orig, pois = future_poison_test(dd, computation, cutoff="15:55")
            poison_results.append({
                "date": dd.name,
                "decision_time": t,
                "passed": passed,
                "orig_signed_ret": orig.get("signed_ret_pct") if orig else None,
                "poisoned_signed_ret": pois.get("signed_ret_pct") if pois else None,
            })

    all_passed = all(r["passed"] for r in poison_results)
    logger.info(f"Future-poison test: {'PASSED' if all_passed else 'FAILED'}")

    # === Build report ===
    out = [
        "# Day 1 Intraday Labels — MVP Plan\n",
        f"Generated: {datetime.now().isoformat()}",
        f"Days processed: {df['date'].nunique()}",
        f"Rows (2 decision times × valid days): {len(df)}",
        "",
        "## Labels (decision time t → 15:55 ET)",
        "- `signed_ret_pct` = (spot_end − spot_t) / spot_t × 100",
        "- `abs_ret_pct` = |signed_ret_pct|",
        "- `realized_var` = Σ (1-min log return)² on [t, 15:55]",
        "- NO next-day labels.",
        "",
        "## Label distribution (primary t=15:00)",
    ]
    prim = df[df["decision_time"] == "15:00"]
    out.append(prim[["signed_ret_pct", "abs_ret_pct", "realized_var"]].describe().round(5).to_markdown())
    out.append("")

    out.append("## Label distribution (robustness t=14:30)")
    rob = df[df["decision_time"] == "14:30"]
    out.append(rob[["signed_ret_pct", "abs_ret_pct", "realized_var"]].describe().round(5).to_markdown())
    out.append("")

    out.append("## By year (primary t=15:00)")
    out.append(prim.groupby("year")[["signed_ret_pct", "abs_ret_pct", "realized_var"]].mean().round(4).to_markdown())
    out.append("")

    out.append("## Leak-safety verification (future-poison after 15:55)")
    out.append(f"**Status**: {'✅ ALL PASSED' if all_passed else '❌ FAILED'}\n")
    out.append(pd.DataFrame(poison_results).to_markdown(index=False))
    out.append("")

    out.append("## Sanity sample: first 5 days primary labels")
    out.append(prim.head().to_markdown(index=False))
    out.append("")

    # Coverage check
    out.append("## Coverage check")
    out.append(f"- Days with primary (15:00) label: {len(prim)}")
    out.append(f"- Days with robustness (14:30) label: {len(rob)}")
    out.append(f"- Days with both: {len(set(prim['date']) & set(rob['date']))}")

    # Describe bars per day
    out.append(f"- Median n_bars t=15:00→15:55: {prim['n_bars'].median()}")
    out.append(f"- Median n_bars t=14:30→15:55: {rob['n_bars'].median()}")
    out.append("")

    REPORT.write_text("\n".join(out))
    logger.info(f"Report: {REPORT}")
    print("\n".join(out[:30]))
    print("...")


if __name__ == "__main__":
    main()
