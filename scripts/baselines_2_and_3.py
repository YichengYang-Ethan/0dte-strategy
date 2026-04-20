"""Baselines 2 and 3, run together for comparison.

Baseline 2: Prior-close GEX skew (call_gamma − put_gamma × OI) → next-day SPX direction.
  Thesis: Dealer gamma imbalance at close is sufficient structural info. No trade
  classification, no aggressor signing. Uses only OI × gamma × spot² per strike.

Baseline 3: Last 30-min SPX momentum (up to 15:55) → next-day SPX direction.
  Thesis: Intraday end-of-day momentum carries to next day.
  Uses NO option data — pure SPX spot.

Both use leak-safe primitives:
  - spot: last underlying_price ≤ 15:55 ET
  - rolling z-score: 60d trailing, shift-1
  - target: next-day close-to-close using same 15:55 spot

Signal: |z| ≥ 0.5 threshold
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
    DEFAULT_CUTOFF_ET,
    close_spot_leak_safe,
    rolling_zscore_shifted,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("b2b3")

DATA_DIR = Path("/Users/ethanyang/0dte-strategy/data/historical_0dte")
REPORT = Path("/Users/ethanyang/0dte-strategy/logs/baselines_2_3_report.md")

THRESHOLD = 0.5
ROLLING_WINDOW = 60


# ---------------------------------------------------------------------------
# Baseline 2 helpers: GEX skew from prior-close OI × gamma
# ---------------------------------------------------------------------------

def compute_gex_skew_leak_safe(day_dir: Path, cutoff: str = DEFAULT_CUTOFF_ET) -> dict | None:
    """Aggregate GEX skew (call - put) using OI from same day + greeks at cutoff.

    GEX_contract = OI × gamma × 100 × spot²
    Returns: date, gex_call_side, gex_put_side, gex_skew, spot_used
    """
    d = datetime.strptime(day_dir.name.split("=")[1], "%Y-%m-%d").date()

    # Load OI (daily, not time-sensitive)
    oi_files = sorted((day_dir / "oi").glob("*.parquet"))
    if not oi_files:
        return None
    oi = pd.concat([pd.read_parquet(f) for f in oi_files], ignore_index=True)
    if oi.empty:
        return None

    # Load greeks, filter to cutoff, aggregate last value per contract before cutoff
    greeks_files = sorted((day_dir / "greeks").glob("*.parquet"))
    if not greeks_files:
        return None

    greeks_rows = []
    for f in greeks_files:
        try:
            df = pd.read_parquet(f, columns=["timestamp", "strike", "right", "gamma", "underlying_price"])
            df = df[df["timestamp"].str.slice(11, 16) <= cutoff]
            df = df[df["underlying_price"] > 0]
            if df.empty:
                continue
            # Last value per contract at cutoff
            df = df.sort_values("timestamp").tail(1)
            greeks_rows.append(df)
        except Exception:
            continue

    if not greeks_rows:
        return None
    g = pd.concat(greeks_rows, ignore_index=True)

    # Spot
    spot = g["underlying_price"].median()

    # Join with OI
    merged = oi.merge(g[["strike", "right", "gamma"]], on=["strike", "right"], how="inner")
    if merged.empty:
        return None

    # GEX per contract: OI × gamma × 100 × spot²
    merged["gex"] = merged["open_interest"] * merged["gamma"] * 100 * (spot ** 2)

    gex_call = merged[merged["right"] == "CALL"]["gex"].sum()
    gex_put = merged[merged["right"] == "PUT"]["gex"].sum()

    return {
        "date": d,
        "gex_call": float(gex_call),
        "gex_put": float(gex_put),
        "gex_skew": float(gex_call - gex_put),
        "gex_total": float(gex_call + gex_put),
        "spot_used": float(spot),
    }


# ---------------------------------------------------------------------------
# Baseline 3 helpers: 30-min intraday momentum
# ---------------------------------------------------------------------------

def compute_intraday_momentum(day_dir: Path, cutoff: str = DEFAULT_CUTOFF_ET,
                              window_minutes: int = 30) -> dict | None:
    """Spot-based momentum using underlying_price from greeks parquets.

    momentum = (spot_cutoff - spot_cutoff_minus_window) / spot_cutoff_minus_window
    """
    d = datetime.strptime(day_dir.name.split("=")[1], "%Y-%m-%d").date()

    # Compute both spots using leak-safe primitive
    def time_str_minus(hhmm: str, minutes: int) -> str:
        h, m = int(hhmm[:2]), int(hhmm[3:5])
        total = h * 60 + m - minutes
        if total < 0:
            return "09:30"
        return f"{total // 60:02d}:{total % 60:02d}"

    cutoff_early = time_str_minus(cutoff, window_minutes)
    _, spot_now = close_spot_leak_safe(day_dir, cutoff=cutoff)
    _, spot_early = close_spot_leak_safe(day_dir, cutoff=cutoff_early)

    if np.isnan(spot_now) or np.isnan(spot_early) or spot_early <= 0:
        return None

    momentum = (spot_now - spot_early) / spot_early
    return {
        "date": d,
        "spot_cutoff": spot_now,
        "spot_earlier": spot_early,
        "cutoff_early": cutoff_early,
        "cutoff_now": cutoff,
        "intraday_momentum_pct": momentum * 100,
    }


# ---------------------------------------------------------------------------
# Main aggregation
# ---------------------------------------------------------------------------

def metrics(subset: pd.DataFrame, ret_col: str, sig_col: str) -> dict:
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


def main():
    day_dirs = sorted(DATA_DIR.glob("date=*"))
    logger.info(f"Processing {len(day_dirs)} days for B2 + B3 + close-spot...")

    b2_records = []
    b3_records = []
    close_records = []
    for i, dd in enumerate(day_dirs):
        b2 = compute_gex_skew_leak_safe(dd)
        if b2:
            b2_records.append(b2)
        b3 = compute_intraday_momentum(dd, window_minutes=30)
        if b3:
            b3_records.append(b3)
        d, spot = close_spot_leak_safe(dd)
        close_records.append({"date": d, "close_spot": spot})
        if (i + 1) % 100 == 0:
            logger.info(f"  {i+1}/{len(day_dirs)}")

    b2_df = pd.DataFrame(b2_records)
    b3_df = pd.DataFrame(b3_records)
    close_df = pd.DataFrame(close_records)
    for d in (b2_df, b3_df, close_df):
        d["date"] = pd.to_datetime(d["date"])

    # Merge all into one frame
    df = close_df.merge(b2_df, on="date", how="outer").merge(b3_df, on="date", how="outer")
    df = df.sort_values("date").reset_index(drop=True)
    df["year"] = df["date"].dt.year

    # Target: next-day close-to-close return
    df["next_close_spot"] = df["close_spot"].shift(-1)
    df["next_day_ret_pct"] = (df["next_close_spot"] - df["close_spot"]) / df["close_spot"] * 100
    df = df.dropna(subset=["next_day_ret_pct"])

    # Baseline 2: z-score GEX skew
    df["gex_skew_z"] = rolling_zscore_shifted(df["gex_skew"], ROLLING_WINDOW)
    df["b2_signal"] = np.where(
        df["gex_skew_z"] >= THRESHOLD, 1,
        np.where(df["gex_skew_z"] <= -THRESHOLD, -1, 0)
    )
    df["b2_return"] = df["b2_signal"] * df["next_day_ret_pct"]

    # Baseline 3: z-score intraday momentum
    df["intraday_mom_z"] = rolling_zscore_shifted(df["intraday_momentum_pct"], ROLLING_WINDOW)
    df["b3_signal"] = np.where(
        df["intraday_mom_z"] >= THRESHOLD, 1,
        np.where(df["intraday_mom_z"] <= -THRESHOLD, -1, 0)
    )
    df["b3_return"] = df["b3_signal"] * df["next_day_ret_pct"]

    df_eval = df.dropna(subset=["gex_skew_z", "intraday_mom_z"])
    logger.info(f"Evaluation days (after rolling warmup): {len(df_eval)}")

    df.to_parquet("/Users/ethanyang/0dte-strategy/data/baselines_2_3.parquet", compression="zstd")

    # Metrics
    m_b2 = metrics(df_eval, "b2_return", "b2_signal")
    m_b3 = metrics(df_eval, "b3_return", "b3_signal")
    uncond_ret = df_eval["next_day_ret_pct"]
    uncond_sharpe = uncond_ret.mean() / uncond_ret.std() * np.sqrt(252)
    uncond_wr = (uncond_ret > 0).sum() / len(uncond_ret) * 100

    # Direction accuracy
    acc_b2 = (np.sign(df_eval["gex_skew_z"]) == np.sign(df_eval["next_day_ret_pct"])).sum() / len(df_eval) * 100
    acc_b3 = (np.sign(df_eval["intraday_mom_z"]) == np.sign(df_eval["next_day_ret_pct"])).sum() / len(df_eval) * 100

    # Report
    out = [
        "# Baselines 2 & 3 — Leak-Safe Falsification Results\n",
        f"Generated: {datetime.now().isoformat()}",
        f"Evaluation days: {len(df_eval)}",
        f"Cutoff: {DEFAULT_CUTOFF_ET} ET | Rolling: {ROLLING_WINDOW}d shift-1 | Threshold: |z| ≥ {THRESHOLD}",
        "",
        "All signal computations use `src/pipeline/leak_safe.py` primitives.",
        "",
        "## 1. Summary Table — All Baselines",
        "| Baseline | Signal | N | WR | Dir Acc | Mean | Sharpe | PF | vs Uncond |",
        "|----------|--------|---|-----|---------|------|--------|-----|-----------|",
        f"| Unconditional long SPX | — | {len(df_eval)} | {uncond_wr:.1f}% | 50% | {uncond_ret.mean():+.3f}% | **{uncond_sharpe:.2f}** | — | 0.00 |",
        f"| **B1 v3** signed flow (recap) | quote-rule z-score | 592 | 53.7% | 52.0% | +0.025% | 0.41 | 1.08 | -0.53 |",
        f"| **B2** GEX skew (new) | OI×gamma z-score | {m_b2['n']} | {m_b2['wr']:.1f}% | {acc_b2:.1f}% | {m_b2['mean']:+.3f}% | **{m_b2['sharpe']:.2f}** | {m_b2['pf']:.2f} | {m_b2['sharpe']-uncond_sharpe:+.2f} |",
        f"| **B3** 30-min momentum (new) | spot return z-score | {m_b3['n']} | {m_b3['wr']:.1f}% | {acc_b3:.1f}% | {m_b3['mean']:+.3f}% | **{m_b3['sharpe']:.2f}** | {m_b3['pf']:.2f} | {m_b3['sharpe']-uncond_sharpe:+.2f} |",
        "",
    ]

    # B2 by year
    out.append("## 2. Baseline 2 (GEX skew) by Year")
    out.append("| Year | N | WR | Mean | Sharpe | PF |")
    out.append("|------|---|-----|------|--------|-----|")
    for y, sub in df_eval.groupby("year"):
        m = metrics(sub, "b2_return", "b2_signal")
        out.append(f"| {y} | {m['n']} | {m['wr']:.1f}% | {m['mean']:+.3f}% | {m['sharpe']:.2f} | {m['pf']:.2f} |")
    out.append("")

    # B3 by year
    out.append("## 3. Baseline 3 (intraday momentum) by Year")
    out.append("| Year | N | WR | Mean | Sharpe | PF |")
    out.append("|------|---|-----|------|--------|-----|")
    for y, sub in df_eval.groupby("year"):
        m = metrics(sub, "b3_return", "b3_signal")
        out.append(f"| {y} | {m['n']} | {m['wr']:.1f}% | {m['mean']:+.3f}% | {m['sharpe']:.2f} | {m['pf']:.2f} |")
    out.append("")

    # Signal distribution
    out.append("## 4. Signal Distributions")
    b2_sv = df_eval["b2_signal"].value_counts().to_dict()
    b3_sv = df_eval["b3_signal"].value_counts().to_dict()
    out.append(f"- B2: Long {b2_sv.get(1,0)}, Short {b2_sv.get(-1,0)}, No signal {b2_sv.get(0,0)}")
    out.append(f"- B3: Long {b3_sv.get(1,0)}, Short {b3_sv.get(-1,0)}, No signal {b3_sv.get(0,0)}")
    out.append("")

    # Verdict
    out.append("## 5. Verdict")
    best = max([("B1 v3", 0.41), ("B2", m_b2["sharpe"]), ("B3", m_b3["sharpe"])], key=lambda x: x[1])
    out.append(f"- Best signal-strategy Sharpe: **{best[0]}** at **{best[1]:.2f}**")
    out.append(f"- Unconditional Sharpe: **{uncond_sharpe:.2f}**")
    out.append(f"- Excess over unconditional: **{best[1] - uncond_sharpe:+.2f}**")
    out.append("")
    if best[1] - uncond_sharpe > 0.3:
        out.append(f"**VERDICT**: {best[0]} surpasses unconditional by >0.3 Sharpe. Proceed to block bootstrap CI.")
    else:
        out.append("**VERDICT**: None of B1/B2/B3 surpasses unconditional-long by a meaningful margin. All three dumb baselines fail. Revisit thesis OR instrument.")

    REPORT.write_text("\n".join(out))
    logger.info(f"Report: {REPORT}")
    print("\n".join(out))


if __name__ == "__main__":
    main()
