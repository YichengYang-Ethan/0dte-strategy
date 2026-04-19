"""v6 regime re-diagnosis with real Theta Greeks.

My v4 NEG_GAMMA label came from BSM-recomputed gamma over all rows. With real
Theta Greeks (+real IV) now available, the GEX profile may be materially
different (IV surface curvature → gamma curvature).

Questions this script answers:
1. Regime distribution: did NEG/POS_GAMMA split change? (was 73 NEG / 40 POS on 232 d)
2. Call/put wall positions: did they move?
3. pos<0.15 trigger rate: roughly same (134 in 574)?
4. If regime labels shift substantially, v4's 3-tier validation is compromised
   (my "OOS" was using BSM labels, not real labels).

No strategy changes — pure observational diagnosis.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date, datetime
from pathlib import Path
import numpy as np
import pandas as pd

from src.gex.calculator import calculate_gex_profile, identify_levels

ORIG_IS_START = date(2025, 10, 31)
ORIG_OOS_START = date(2025, 5, 15)


def bucket(d):
    if d >= ORIG_IS_START: return "ORIG_IS"
    if d >= ORIG_OOS_START: return "ORIG_OOS"
    return "EXT_OOS"


def main():
    files = sorted(Path("data/historical/spy").glob("*.parquet"))
    rows = []
    regime_change_days = []

    for fp in files:
        try:
            d = datetime.strptime(fp.stem, "%Y%m%d").date()
        except ValueError:
            continue
        bar = pd.read_parquet(fp)
        if bar.empty or "spot" not in bar.columns:
            continue
        is_v2 = "theta_greek" in bar.columns
        spot = float(bar["spot"].dropna().iloc[0])

        # Filter to ≤45 DTE to match engine behavior
        if "dte_years" in bar.columns:
            near = bar[bar["dte_years"] * 365 <= 45]
        else:
            near = bar

        # Use raw gamma × OI × 100 × S² × 0.01 directly from columns
        gex_profile = calculate_gex_profile(near, spot)
        lv = identify_levels(gex_profile, spot)

        pos = None
        if lv.call_wall and lv.put_wall and lv.call_wall > lv.put_wall:
            pos = (spot - lv.put_wall) / (lv.call_wall - lv.put_wall)

        rows.append({
            "date": d, "bucket": bucket(d), "is_v2": is_v2,
            "spot": spot, "regime": lv.regime,
            "call_wall": lv.call_wall, "put_wall": lv.put_wall,
            "total_gex": lv.total_gex, "pos": pos,
            "trigger_v4": (lv.regime == "NEGATIVE_GAMMA" and pos is not None and pos < 0.15),
        })

    df = pd.DataFrame(rows)
    print(f"=== Regime diagnosis (all 574 days) ===\n")
    print(f"Total days: {len(df)}")
    print(f"v2-enriched: {df['is_v2'].sum()}/{len(df)}")
    print()
    print("By bucket × regime:")
    xt = df.pivot_table(index="bucket", columns="regime", values="date", aggfunc="count", fill_value=0)
    print(xt)
    print()
    print("pos<0.15 trigger rate by bucket:")
    print(df.groupby("bucket")["trigger_v4"].agg(["sum", "count", "mean"]))
    print()
    print("Per-regime days where v2 vs v1 labels might differ (if mixed):")
    print(df.groupby(["bucket", "is_v2", "regime"])["date"].count().to_frame("n"))


if __name__ == "__main__":
    main()
