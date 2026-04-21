"""V7: v5 signal stop-loss sensitivity — 40% / 50% (default) / 60%.

V2 empirically showed -40% stop maximizes PF on UNCONDITIONAL 0.20Δ
calls (PF 1.28 vs 0.97 no-stop). But our v5 uses 0.70Δ ITM calls under
NEG_GAMMA + pos<0.15 signal. This is a different payoff structure;
conclusions from V2 don't transfer automatically.

Test: run v5 backtest under three sl_pct values and compare:
  - sl_pct = -0.40  (Joey)
  - sl_pct = -0.50  (current v5 default)
  - sl_pct = -0.60
on each OOS bucket: ORIG_IS, ORIG_OOS, EXT_OOS, ALL.

ROI justification: one-line config change; if -0.40 improves PF
uniformly across buckets, we get free alpha. If -0.50 is optimal or
regime-dependent, we learn our signal's stop sensitivity differs from
unconditional.

Not a kill test — diagnostic only.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
logging.basicConfig(level=logging.WARNING)

from src.backtest.engine import BacktestConfig, BacktestEngine  # noqa: E402

OUT_DIR = REPO_ROOT / "logs"
OUT_DIR.mkdir(exist_ok=True)

ORIG_IS_START = date(2025, 10, 31)
ORIG_OOS_START = date(2025, 5, 15)

STOP_LEVELS = [-0.40, -0.50, -0.60]


def bucket(d: date) -> str:
    if d >= ORIG_IS_START:
        return "ORIG_IS"
    if d >= ORIG_OOS_START:
        return "ORIG_OOS"
    return "EXT_OOS"


def compute_metrics(df: pd.DataFrame) -> dict | None:
    if df.empty:
        return None
    wins = int((df["pnl"] > 0).sum())
    pf_den = -float(df[df["pnl"] < 0]["pnl"].sum())
    pf_num = float(df[df["pnl"] > 0]["pnl"].sum())
    pf = pf_num / pf_den if pf_den > 0 else float("inf")
    cum = df["pnl"].cumsum().to_numpy()
    peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    std = float(df["pnl"].std())
    sharpe = (float(df["pnl"].mean()) / std * np.sqrt(252)) if std > 0 else 0.0
    return {
        "N": int(len(df)),
        "WR": round(wins / len(df) * 100, 2),
        "PnL": round(float(df["pnl"].sum()), 0),
        "PF": round(float(pf), 3) if np.isfinite(pf) else "inf",
        "DD": round(dd, 0),
        "Sharpe": round(float(sharpe), 3),
    }


def run_stop(sl_pct: float) -> pd.DataFrame:
    cfg = BacktestConfig(contracts_per_trade=1, sl_pct=sl_pct)
    df = BacktestEngine(cfg).run("data/historical/spy", mode="swing_1dte")
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.date
    df["bucket"] = df["trade_date"].apply(bucket)
    return df


def main() -> int:
    results: dict = {}
    for sl in STOP_LEVELS:
        print(f"\n=== Running v5 with sl_pct={sl:+.2f} ===", file=sys.stderr)
        df = run_stop(sl)
        if df.empty:
            print(f"  no trades at sl={sl}", file=sys.stderr)
            continue
        bucket_results = {}
        for b in ["ORIG_IS", "ORIG_OOS", "EXT_OOS", "ALL"]:
            sub = df if b == "ALL" else df[df["bucket"] == b]
            m = compute_metrics(sub)
            if m is None:
                continue
            bucket_results[b] = m
            print(f"  {b:10s} | N={m['N']:3d} WR={m['WR']:5.1f}% "
                  f"PnL=${m['PnL']:+7.0f} PF={m['PF']} Sharpe={m['Sharpe']}")
        results[f"sl={sl:+.2f}"] = bucket_results

    # Comparison table
    print("\n\n=== PF comparison across stop levels ===")
    print(f"{'Bucket':<12}", end="")
    for sl in STOP_LEVELS:
        print(f"{'sl=' + f'{sl:+.2f}':>12}", end="")
    print()
    for b in ["ORIG_IS", "ORIG_OOS", "EXT_OOS", "ALL"]:
        print(f"{b:<12}", end="")
        for sl in STOP_LEVELS:
            key = f"sl={sl:+.2f}"
            r = results.get(key, {}).get(b)
            pf = r["PF"] if r else "-"
            print(f"{pf!s:>12}", end="")
        print()

    out_json = OUT_DIR / "v7_stop_sensitivity_result.json"
    with out_json.open("w") as f:
        json.dump(results, f, indent=2)
    print(f"\nsaved: {out_json}")

    # Verdict
    print("\n=== Verdict ===")
    pf_all = {
        sl: results.get(f"sl={sl:+.2f}", {}).get("ALL", {}).get("PF", 0)
        for sl in STOP_LEVELS
    }
    best = max(pf_all, key=lambda k: pf_all[k] if isinstance(pf_all[k], (int, float)) else 0)
    current_default = -0.50
    if best == current_default:
        print(f"  Current default sl=-0.50 is best on ALL bucket.")
    elif best == -0.40:
        pf_40 = pf_all[-0.40]
        pf_50 = pf_all[-0.50]
        delta = ((pf_40 - pf_50) / pf_50 * 100) if pf_50 else 0
        print(f"  Joey's sl=-0.40 beats current default on ALL: "
              f"PF {pf_40} vs {pf_50} ({delta:+.1f}%).")
        print(f"  Check per-bucket consistency before changing BacktestConfig default.")
    else:
        print(f"  sl=-0.60 is best on ALL. Unexpected — investigate.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
