"""Day 3 of GPT Pro MVP plan — post-diagnostic (Day 2.5) verdict.

GPT Pro Day 2.5 verdict: direction branch is confirmatory FALSIFICATION;
volatility branch is EXPLORATORY (not confirmatory — labels were pre-computed
but target choice was data-contingent, so full-family 12-test Bonferroni
applies, and volatility results carry the exploratory flag).

Branches:

BRANCH A — Direction (CONFIRMATORY, as pre-registered against signed_ret_pct):
  B1 flow-only:        sign(flow_delta_net_30m_z)  → predict sign(signed_ret_pct)
  B2 state-only:       sign(atm_gex_skew_z)        → predict sign(signed_ret_pct)
  B3 interaction-only: interaction_sign            → predict sign(signed_ret_pct)
  B4 inverse-B3:      -interaction_sign            → predict sign(signed_ret_pct)

BRANCH B — Volatility (EXPLORATORY, primary=realized_var, robustness=abs_ret_pct):
  V1 state-only:       atm_gex_skew_z              → predict realized_var
  V2 flow-only:        |flow_gamma_net_30m|_z      → predict realized_var
  V3 interaction-only: interaction_weighted_z      → predict realized_var
  V4 persistence:      pre_signal_realized_var     → predict realized_var
       (this is the volatility sanity benchmark; V1-V3 must beat it
        in incremental R² to matter.)

All features z-scored with rolling shift-1 (60d window) per leak-safe primitives.
Decision time = 15:00. First 60 days dropped for z-score warmup.

Multiple-testing: family size = 12 (4 direction × 1 target + 4 vol × 2 targets).
"""
from __future__ import annotations
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from scipy import stats

from src.pipeline.leak_safe import (
    rolling_zscore_shifted,
    intraday_spot_series_leak_safe,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("day3")

DATA_DIR_RAW = Path("/Users/ethanyang/0dte-strategy/data/historical_0dte")
DATA_DIR = Path("/Users/ethanyang/0dte-strategy/data")
REPORT = Path("/Users/ethanyang/0dte-strategy/logs/intraday_day3_report.md")

FAMILY_SIZE = 12
Z_WARMUP = 60


# ---------------------------------------------------------------------------
# Pre-signal realized variance (persistence baseline)
# ---------------------------------------------------------------------------

def pre_signal_realized_var(day_dir: Path, t: str = "15:00") -> float:
    """Realized variance in [09:30, t] — leak-safe since t is the decision time.

    Used as persistence baseline for predicting post-t realized variance.
    """
    series = intraday_spot_series_leak_safe(day_dir, start="09:30", end=t)
    if len(series) < 2:
        return np.nan
    log_ret = np.log(series["spot"]).diff().dropna()
    return float((log_ret ** 2).sum())


def build_persistence_series() -> pd.DataFrame:
    day_dirs = sorted(DATA_DIR_RAW.glob("date=*"))
    logger.info(f"Computing pre-signal realized variance for {len(day_dirs)} days...")
    records = []
    for i, dd in enumerate(day_dirs):
        d = datetime.strptime(dd.name.split("=")[1], "%Y-%m-%d").date()
        rv = pre_signal_realized_var(dd, t="15:00")
        records.append({"date": d, "decision_time": "15:00", "pre_signal_realized_var": rv})
        if (i + 1) % 100 == 0:
            logger.info(f"  pre-signal rv: {i+1}/{len(day_dirs)}")
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Helpers for baselines
# ---------------------------------------------------------------------------

def sign_concordance(signal: pd.Series, target: pd.Series) -> tuple[float, int, float]:
    """Returns (concordance_pct, n_valid, one-sided binomial p-value)."""
    mask = (signal != 0) & (~signal.isna()) & (~target.isna()) & (target != 0)
    s = signal[mask]
    t = target[mask]
    if len(s) == 0:
        return (np.nan, 0, np.nan)
    match = (np.sign(s) == np.sign(t)).sum()
    n = len(s)
    p = stats.binomtest(int(match), n, p=0.5, alternative="greater").pvalue
    return (match / n * 100, n, p)


def sign_strategy_sharpe(signal: pd.Series, signed_ret: pd.Series) -> float:
    """Annualized Sharpe of daily returns = sign(signal) × signed_ret_pct."""
    mask = (signal != 0) & (~signal.isna()) & (~signed_ret.isna())
    s = signal[mask]
    r = signed_ret[mask]
    if len(s) < 30:
        return np.nan
    daily_pnl = np.sign(s).values * r.values
    mu, sigma = daily_pnl.mean(), daily_pnl.std()
    if sigma == 0:
        return np.nan
    return float(mu / sigma * np.sqrt(252))


def incremental_r2(feature: pd.Series, target: pd.Series, persistence: pd.Series) -> dict:
    """Incremental R² of feature over persistence-only baseline for target."""
    mask = (~feature.isna()) & (~target.isna()) & (~persistence.isna())
    x1, x2, y = persistence[mask], feature[mask], target[mask]
    if len(y) < 100:
        return {"r2_persistence": np.nan, "r2_combined": np.nan, "delta_r2": np.nan, "n": len(y)}
    # R² persistence only
    X1 = np.column_stack([np.ones(len(x1)), x1.values])
    b1, *_ = np.linalg.lstsq(X1, y.values, rcond=None)
    yhat1 = X1 @ b1
    ss_res1 = ((y.values - yhat1) ** 2).sum()
    ss_tot = ((y.values - y.values.mean()) ** 2).sum()
    r2_p = 1 - ss_res1 / ss_tot
    # R² combined
    X2 = np.column_stack([np.ones(len(x1)), x1.values, x2.values])
    b2, *_ = np.linalg.lstsq(X2, y.values, rcond=None)
    yhat2 = X2 @ b2
    ss_res2 = ((y.values - yhat2) ** 2).sum()
    r2_c = 1 - ss_res2 / ss_tot
    return {
        "r2_persistence": float(r2_p),
        "r2_combined": float(r2_c),
        "delta_r2": float(r2_c - r2_p),
        "n": int(len(y)),
    }


def quintile_spread(feature: pd.Series, target: pd.Series) -> dict:
    """Q1 vs Q5 mean of target sorted by feature. Returns monotonicity check."""
    mask = (~feature.isna()) & (~target.isna())
    df = pd.DataFrame({"f": feature[mask], "y": target[mask]})
    if len(df) < 50:
        return {"q1": np.nan, "q5": np.nan, "spread": np.nan, "monotonic": False}
    df["q"] = pd.qcut(df["f"], 5, labels=False, duplicates="drop")
    means = df.groupby("q")["y"].mean().values
    if len(means) < 5:
        return {"q1": np.nan, "q5": np.nan, "spread": np.nan, "monotonic": False}
    # Monotonic if sorted same as 0..4 or reversed
    monotonic = (
        all(means[i] <= means[i + 1] for i in range(4))
        or all(means[i] >= means[i + 1] for i in range(4))
    )
    return {
        "q1": float(means[0]),
        "q5": float(means[4]),
        "spread": float(means[4] - means[0]),
        "monotonic": bool(monotonic),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    labels = pd.read_parquet(DATA_DIR / "intraday_labels.parquet")
    features = pd.read_parquet(DATA_DIR / "intraday_features.parquet")
    labels["date"] = pd.to_datetime(labels["date"])
    features["date"] = pd.to_datetime(features["date"])

    # Persistence baseline cache
    persistence_cache = DATA_DIR / "pre_signal_realized_var.parquet"
    if persistence_cache.exists():
        persistence = pd.read_parquet(persistence_cache)
        persistence["date"] = pd.to_datetime(persistence["date"])
        logger.info(f"Loaded cached persistence: {len(persistence)} rows")
    else:
        persistence = build_persistence_series()
        persistence["date"] = pd.to_datetime(persistence["date"])
        persistence.to_parquet(persistence_cache, compression="zstd")
        logger.info(f"Saved persistence cache: {persistence_cache}")

    # Merge everything on (date, decision_time), filter to t=15:00 primary
    df = (
        features.merge(labels[["date", "decision_time", "signed_ret_pct",
                               "abs_ret_pct", "realized_var"]],
                       on=["date", "decision_time"], how="inner")
        .merge(persistence, on=["date", "decision_time"], how="left")
    )
    df = df[df["decision_time"] == "15:00"].sort_values("date").reset_index(drop=True)
    logger.info(f"Primary (15:00) panel: {len(df)} rows")

    # --- Rolling z-score shift-1 on key features (60d window) ---
    feature_cols = [
        "flow_delta_net_30m", "flow_gamma_net_30m",
        "atm_gex_skew", "interaction_weighted",
    ]
    for c in feature_cols:
        df[f"{c}_z"] = rolling_zscore_shifted(df[c], window=Z_WARMUP)
    # abs |flow_gamma_net_30m| for vol (magnitude)
    df["flow_gamma_abs_30m"] = df["flow_gamma_net_30m"].abs()
    df["flow_gamma_abs_30m_z"] = rolling_zscore_shifted(df["flow_gamma_abs_30m"], window=Z_WARMUP)

    # Drop warmup
    df_eval = df.iloc[Z_WARMUP:].copy()
    logger.info(f"After z-warmup drop: {len(df_eval)} rows "
                f"({df_eval['date'].min().date()} → {df_eval['date'].max().date()})")

    # Year tagging for stability checks
    df_eval["year"] = df_eval["date"].dt.year

    # ====================================================================
    # BRANCH A — Direction baselines (CONFIRMATORY)
    # ====================================================================
    logger.info("=== BRANCH A: Direction baselines (confirmatory) ===")

    # Interaction sign is already ±1 / 0, no z-score needed
    direction_baselines = {
        "B1_flow_only":      df_eval["flow_delta_net_30m_z"],
        "B2_state_only":     df_eval["atm_gex_skew_z"],
        "B3_interaction":    df_eval["interaction_sign"],
        "B4_inverse_B3":   -(df_eval["interaction_sign"]),
    }

    direction_rows = []
    for name, sig in direction_baselines.items():
        conc, n, p = sign_concordance(sig, df_eval["signed_ret_pct"])
        sharpe = sign_strategy_sharpe(sig, df_eval["signed_ret_pct"])
        # By-year concordance (robustness)
        by_year = {}
        for y, sub in df_eval.groupby("year"):
            ssig = sig.loc[sub.index]
            c, _, _ = sign_concordance(ssig, sub["signed_ret_pct"])
            by_year[int(y)] = round(c, 2) if not np.isnan(c) else None
        direction_rows.append({
            "baseline": name,
            "concordance_pct": round(conc, 2),
            "n": n,
            "p_raw": round(p, 4),
            "p_bonf_12": round(min(p * FAMILY_SIZE, 1.0), 4),
            "sharpe_annual": round(sharpe, 3) if not np.isnan(sharpe) else None,
            "by_year": by_year,
        })

    # ====================================================================
    # BRANCH B — Volatility baselines (EXPLORATORY)
    # ====================================================================
    logger.info("=== BRANCH B: Volatility baselines (EXPLORATORY) ===")

    vol_features = {
        "V1_state_only":     df_eval["atm_gex_skew_z"],
        "V2_flow_magnitude": df_eval["flow_gamma_abs_30m_z"],
        "V3_interaction":    df_eval["interaction_weighted_z"],
        # V4 persistence uses raw pre_signal_realized_var (not z)
    }
    persistence_raw = df_eval["pre_signal_realized_var"]

    vol_targets = {
        "realized_var_primary": df_eval["realized_var"],
        "abs_ret_pct_robust":   df_eval["abs_ret_pct"],
    }

    vol_rows = []

    # V4 persistence — direct baseline: R² of persistence alone per target
    for tgt_name, tgt in vol_targets.items():
        m = (~persistence_raw.isna()) & (~tgt.isna())
        r_p, p_p = stats.pearsonr(persistence_raw[m], tgt[m])
        r_s, _ = stats.spearmanr(persistence_raw[m], tgt[m])
        qs = quintile_spread(persistence_raw, tgt)
        vol_rows.append({
            "baseline": "V4_persistence",
            "target": tgt_name,
            "n": int(m.sum()),
            "pearson_r": round(r_p, 4),
            "spearman_r": round(r_s, 4),
            "p_raw": round(p_p, 4),
            "p_bonf_12": round(min(p_p * FAMILY_SIZE, 1.0), 4),
            "q1_mean": round(qs["q1"], 6),
            "q5_mean": round(qs["q5"], 6),
            "q5_q1_spread": round(qs["spread"], 6),
            "monotonic": qs["monotonic"],
            "delta_r2_vs_persistence": 0.0,
        })

    # V1-V3 — incremental contribution over persistence
    for feat_name, feat_sig in vol_features.items():
        for tgt_name, tgt in vol_targets.items():
            m = (~feat_sig.isna()) & (~tgt.isna())
            r_p, p_p = stats.pearsonr(feat_sig[m], tgt[m])
            r_s, _ = stats.spearmanr(feat_sig[m], tgt[m])
            qs = quintile_spread(feat_sig, tgt)
            inc = incremental_r2(feat_sig, tgt, persistence_raw)
            vol_rows.append({
                "baseline": feat_name,
                "target": tgt_name,
                "n": int(m.sum()),
                "pearson_r": round(r_p, 4),
                "spearman_r": round(r_s, 4),
                "p_raw": round(p_p, 4),
                "p_bonf_12": round(min(p_p * FAMILY_SIZE, 1.0), 4),
                "q1_mean": round(qs["q1"], 6),
                "q5_mean": round(qs["q5"], 6),
                "q5_q1_spread": round(qs["spread"], 6),
                "monotonic": qs["monotonic"],
                "delta_r2_vs_persistence": round(inc["delta_r2"], 5),
            })

    # ====================================================================
    # Build report
    # ====================================================================
    dir_df = pd.DataFrame(direction_rows)
    vol_df = pd.DataFrame(vol_rows)

    out = [
        "# Day 3 Baselines — MVP Plan (post-Day-2.5 verdict)\n",
        f"Generated: {datetime.now().isoformat()}",
        f"Decision time: 15:00 (primary)",
        f"Evaluation rows: {len(df_eval)} "
        f"({df_eval['date'].min().date()} → {df_eval['date'].max().date()})",
        f"Rolling z-score warmup: {Z_WARMUP} days (trailing, shift-1)",
        f"Multiple-testing family: Bonferroni, N = {FAMILY_SIZE}",
        "",
        "## GPT Pro Day 2.5 verdict applied",
        "- **Direction branch = CONFIRMATORY falsification** (original pre-registration).",
        "- **Volatility branch = EXPLORATORY** (target choice data-contingent after diagnostic peek).",
        "- Full 12-test Bonferroni correction applied across both branches.",
        "- Primary volatility target: `realized_var`.  Robustness: `abs_ret_pct`.",
        "- All V1-V3 must beat **V4 persistence** in incremental R² to be interesting.",
        "",
        "## BRANCH A — Direction (CONFIRMATORY)",
        "",
        "Target: `signed_ret_pct`.  Metric: sign concordance vs 50% random.",
        "Baselines are run exactly as pre-registered in MVP plan; these are expected to",
        "fail per Day 2.5 diagnostic (max concordance 52.07%).",
        "",
        dir_df.drop(columns=["by_year"]).to_markdown(index=False),
        "",
        "### By-year concordance",
        "",
    ]
    for row in direction_rows:
        out.append(f"- **{row['baseline']}**: {row['by_year']}")
    out.append("")

    out += [
        "## BRANCH B — Volatility (EXPLORATORY)",
        "",
        "Targets: `realized_var` (primary), `abs_ret_pct` (robustness).",
        "Reporting as exploratory per GPT Pro verdict. V4 persistence is the",
        "sanity floor: V1-V3 must add incremental R² > 0 over persistence alone.",
        "",
        vol_df.to_markdown(index=False),
        "",
    ]

    # ====================================================================
    # Verdict block
    # ====================================================================
    max_dir_conc = dir_df["concordance_pct"].max()
    max_dir_sharpe = dir_df["sharpe_annual"].dropna().abs().max() if dir_df["sharpe_annual"].notna().any() else None

    # Best V1-V3 by delta_r2 on primary target
    v_primary = vol_df[(vol_df["target"] == "realized_var_primary")
                      & (vol_df["baseline"].isin(["V1_state_only", "V2_flow_magnitude", "V3_interaction"]))]
    best_delta_r2 = v_primary["delta_r2_vs_persistence"].max() if len(v_primary) else None
    best_v_row = v_primary.loc[v_primary["delta_r2_vs_persistence"].idxmax()] if len(v_primary) else None

    out += [
        "## Verdict",
        "",
        f"**Direction branch:**",
        f"- Max concordance: {max_dir_conc:.2f}% (50% = random)",
        f"- Max |Sharpe|: {max_dir_sharpe}",
        f"- Verdict: "
        + ("**DEAD** (no baseline > 55% concordance or |Sharpe| > 0.5 after Bonferroni)"
           if (max_dir_conc < 55 or (max_dir_sharpe is not None and max_dir_sharpe < 0.5))
           else "**NOT DEAD** (review)"),
        "",
        f"**Volatility branch (EXPLORATORY):**",
    ]
    if best_v_row is not None:
        out += [
            f"- Best feature: {best_v_row['baseline']} vs {best_v_row['target']}",
            f"- Incremental R² over persistence: {best_delta_r2:.5f}",
            f"- Pearson r: {best_v_row['pearson_r']}  | p_bonf_12: {best_v_row['p_bonf_12']}",
            f"- Q5–Q1 spread: {best_v_row['q5_q1_spread']}  | monotonic: {best_v_row['monotonic']}",
            "",
            f"- Verdict: "
            + ("**WORTH DAY 4 PLUMBING CHECK** (adds R² over persistence, exploratory flag)"
               if (best_delta_r2 is not None and best_delta_r2 > 0.005)
               else "**NOT INTERESTING** (does not beat persistence — pre-15:00 realized vol dominates)"),
        ]
    out.append("")

    REPORT.write_text("\n".join(out))
    logger.info(f"Report: {REPORT}")
    print("\n".join(out))


if __name__ == "__main__":
    main()
