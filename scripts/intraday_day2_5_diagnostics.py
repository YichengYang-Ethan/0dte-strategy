"""Day 2.5: Feature-label diagnostic analysis BEFORE running Day 3 baselines.

Not optimization. Not threshold search. Just honest inspection.

For each (feature, label) pair:
  - Pearson correlation + p-value
  - Spearman rank correlation (robust to outliers + regime)
  - Sign concordance: P(sign(feature) == sign(label))
  - Regime breakdown (by year, by IV tercile)
  - Magnitude in tails: does extreme feature predict extreme label?

This surfaces:
  - Whether any feature has MEANINGFUL relationship with labels
  - Which decision time (15:00 vs 14:30) looks better
  - Whether interaction_weighted has signal beyond single-feature
  - Regime-dependence signs
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("diag")

DATA_DIR = Path("/Users/ethanyang/0dte-strategy/data")
REPORT = Path("/Users/ethanyang/0dte-strategy/logs/day2_5_diagnostics.md")


def main():
    labels = pd.read_parquet(DATA_DIR / "intraday_labels.parquet")
    features = pd.read_parquet(DATA_DIR / "intraday_features.parquet")
    labels["date"] = pd.to_datetime(labels["date"])
    features["date"] = pd.to_datetime(features["date"])

    logger.info(f"Labels: {len(labels)} rows, Features: {len(features)} rows")

    # Merge on (date, decision_time)
    df = features.merge(
        labels[["date", "decision_time", "signed_ret_pct", "abs_ret_pct", "realized_var"]],
        on=["date", "decision_time"], how="inner"
    )
    df["year"] = df["date"].dt.year
    logger.info(f"Merged: {len(df)} rows, {len(df.columns)} columns")

    # Feature families to test
    key_features = [
        "flow_delta_net_15m", "flow_delta_net_30m",
        "flow_gamma_net_15m", "flow_gamma_net_30m",
        "hhi_30m", "top1_share_30m", "top3_share_30m",
        "atm_gex_skew", "atm_gex_total",
        "interaction_sign", "interaction_weighted",
    ]
    targets = ["signed_ret_pct", "abs_ret_pct", "realized_var"]

    # Keep only complete rows for correlation analysis
    df_clean = df.dropna(subset=key_features + targets).copy()
    logger.info(f"Clean rows (no NaN): {len(df_clean)}")

    out = [
        "# Day 2.5 Diagnostics — Feature × Label Analysis\n",
        f"Generated: {datetime.now().isoformat()}",
        f"Clean rows: {len(df_clean)}",
        "",
        "**Purpose**: Before running Day 3 pre-registered baselines, inspect whether",
        "any feature has a non-trivial relationship with the intraday targets.",
        "If zero correlation anywhere → baselines are predicted to fail.",
        "",
    ]

    # ---------- 1. Correlation matrix ----------
    out.append("## 1. Feature × Label Correlations (ALL rows, both decision times)\n")
    out.append("Pearson correlation coefficients. |r| > 0.10 is economically interesting at N ~1900.")
    out.append("")
    corr_rows = []
    for feat in key_features:
        row = {"feature": feat}
        for tgt in targets:
            x = df_clean[feat].values
            y = df_clean[tgt].values
            r, p = stats.pearsonr(x, y)
            row[f"{tgt}_r"] = round(r, 4)
            row[f"{tgt}_p"] = round(p, 4)
        corr_rows.append(row)
    out.append(pd.DataFrame(corr_rows).to_markdown(index=False))
    out.append("")

    # ---------- 2. Spearman (rank-based) ----------
    out.append("## 2. Spearman Rank Correlations (robust to outliers)\n")
    corr_rows = []
    for feat in key_features:
        row = {"feature": feat}
        for tgt in targets:
            r, p = stats.spearmanr(df_clean[feat], df_clean[tgt])
            row[f"{tgt}_r"] = round(r, 4)
        corr_rows.append(row)
    out.append(pd.DataFrame(corr_rows).to_markdown(index=False))
    out.append("")

    # ---------- 3. Sign concordance ----------
    out.append("## 3. Sign Concordance: P(sign(feature) == sign(signed_ret_pct))\n")
    out.append("50% = random. >52.5% is mild signal on this N.")
    out.append("")
    sc_rows = []
    for feat in key_features:
        valid = df_clean[(df_clean[feat] != 0) & (df_clean["signed_ret_pct"] != 0)]
        if len(valid) == 0:
            sc_rows.append({"feature": feat, "n": 0, "concordance_pct": None})
            continue
        match = (np.sign(valid[feat]) == np.sign(valid["signed_ret_pct"])).sum()
        sc_rows.append({
            "feature": feat,
            "n": len(valid),
            "concordance_pct": round(match / len(valid) * 100, 2),
        })
    sc_df = pd.DataFrame(sc_rows).sort_values("concordance_pct", ascending=False)
    out.append(sc_df.to_markdown(index=False))
    out.append("")

    # ---------- 4. Primary vs Robustness decision time ----------
    out.append("## 4. Does t=15:00 show stronger signal than t=14:30?\n")
    prim = df_clean[df_clean["decision_time"] == "15:00"]
    rob = df_clean[df_clean["decision_time"] == "14:30"]
    cmp_rows = []
    for feat in key_features:
        r_p, _ = stats.pearsonr(prim[feat], prim["signed_ret_pct"])
        r_r, _ = stats.pearsonr(rob[feat], rob["signed_ret_pct"])
        cmp_rows.append({
            "feature": feat,
            "r_at_15:00": round(r_p, 4),
            "r_at_14:30": round(r_r, 4),
            "delta": round(abs(r_p) - abs(r_r), 4),
        })
    out.append(pd.DataFrame(cmp_rows).to_markdown(index=False))
    out.append("")

    # ---------- 5. Year breakdown for top features ----------
    out.append("## 5. By-Year Correlation (top 3 features by |r| with signed_ret_pct)\n")
    top3 = sc_df.head(3)["feature"].tolist()
    for feat in top3:
        out.append(f"\n### {feat}")
        out.append("| Year | n | Pearson r | Sign concordance % |")
        out.append("|------|---|-----------|--------------------|")
        for y, sub in df_clean.groupby("year"):
            if len(sub) < 30:
                continue
            r, _ = stats.pearsonr(sub[feat], sub["signed_ret_pct"])
            match_mask = (np.sign(sub[feat]) == np.sign(sub["signed_ret_pct"]))
            match = match_mask.sum() / len(sub) * 100
            out.append(f"| {y} | {len(sub)} | {r:+.4f} | {match:.1f}% |")
    out.append("")

    # ---------- 6. Quintile analysis on best feature ----------
    out.append("## 6. Quintile Analysis — Best Feature by |Pearson r|\n")
    all_rs = []
    for feat in key_features:
        r, _ = stats.pearsonr(df_clean[feat], df_clean["signed_ret_pct"])
        all_rs.append((feat, abs(r), r))
    all_rs.sort(key=lambda x: -x[1])
    best_feat, best_abs, best_r = all_rs[0]
    out.append(f"Best feature: **{best_feat}** (Pearson r = {best_r:+.4f})\n")
    df_clean["_quintile"] = pd.qcut(df_clean[best_feat], 5, labels=False, duplicates="drop")
    quint_table = df_clean.groupby("_quintile").agg(
        n=("signed_ret_pct", "size"),
        mean_signed=("signed_ret_pct", "mean"),
        mean_abs=("abs_ret_pct", "mean"),
        mean_var=("realized_var", "mean"),
    ).round(5)
    out.append("| Quintile (of best feature) | n | mean signed_ret | mean abs_ret | mean realized_var |")
    out.append("|---|---|---|---|---|")
    for q, r in quint_table.iterrows():
        out.append(f"| Q{q+1} (lowest → highest) | {r['n']:.0f} | {r['mean_signed']:+.5f} | {r['mean_abs']:.5f} | {r['mean_var']:.6f} |")
    out.append("")

    # ---------- 7. Verdict ----------
    max_abs_r = max(abs_r for _, abs_r, _ in all_rs)
    out.append("## 7. Verdict\n")
    out.append(f"- Max |Pearson r| across all (feature, target): **{max_abs_r:.4f}**")
    out.append(f"- Best pair: {best_feat} vs signed_ret_pct (r={best_r:+.4f})")
    out.append(f"- Max sign concordance: {sc_df.iloc[0]['concordance_pct']}% ({sc_df.iloc[0]['feature']})")
    out.append("")
    if max_abs_r < 0.05:
        out.append("**SIGNAL STRENGTH: NONE.** Max correlation below 0.05. Day 3 baselines are predicted to fail at signal identification. The 0DTE intraday thesis as tested is dead at this horizon/feature set.")
    elif max_abs_r < 0.10:
        out.append("**SIGNAL STRENGTH: MARGINAL.** r in 0.05-0.10 range. Day 3 baselines may show weak Sharpe (0.3-0.8) at best. Proceed with low expectations.")
    elif max_abs_r < 0.20:
        out.append("**SIGNAL STRENGTH: ECONOMICALLY INTERESTING.** r in 0.10-0.20 range. Day 3 baselines worth running. Proceed with moderate expectations.")
    else:
        out.append("**SIGNAL STRENGTH: STRONG.** r > 0.20. Highly unusual for a baseline. Verify no leakage BEFORE running baselines.")

    REPORT.write_text("\n".join(out))
    logger.info(f"Report: {REPORT}")
    print("\n".join(out))


if __name__ == "__main__":
    main()
