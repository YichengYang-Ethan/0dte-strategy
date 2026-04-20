"""Baseline 1: Signed Flow direction predictor.

Research question: Does aggressor-side-signed flow in single-leg LOB 0DTE trades
predict next-day SPX direction?

Per GPT Pro Round 5 + Dong AEA 2026 + EDA findings:
  - Filter to single_leg_electronic trades only (is_single_leg_electronic flag)
  - Classify aggressor via quote-rule: trade price vs last 1-min quote mid
  - Aggregate into net flow: (call buys - call sells) - (put buys - put sells)
    = positive → bullish pressure → predict SPX up tomorrow
  - Z-score by year (EDA found volume grew 3.5x from 2022 to 2026)

Evaluation:
  - Prediction accuracy vs next-day SPX direction
  - Sharpe + PF on signal-day returns
  - Regime-stratified (IV tercile × year)
  - Sensitivity check: exclude 2025-04-07..10 (tariff shock days)
  - Walk-forward: 60d train threshold → next 20d OOS
"""
from __future__ import annotations
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import glob

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("baseline1")

DATA_DIR = Path("/Users/ethanyang/0dte-strategy/data/historical_0dte")
EDA_META = Path("/Users/ethanyang/0dte-strategy/data/eda_day_metadata.parquet")
OUT_PARQUET = Path("/Users/ethanyang/0dte-strategy/data/baseline1_signed_flow.parquet")
REPORT = Path("/Users/ethanyang/0dte-strategy/logs/baseline1_report.md")


def minute_bucket(ts_str: str) -> str:
    """'2024-03-26T09:30:28.123' → '2024-03-26T09:30'"""
    return ts_str[:16]


def compute_day_flow(day_dir: Path) -> dict | None:
    """Compute net signed flow for one day.

    Returns: {
        'date', 'signed_call_vol', 'signed_put_vol', 'signed_net_vol',
        'signed_call_premium', 'signed_put_premium', 'signed_net_premium',
        'n_trades_classified', 'n_trades_total',
    }
    """
    d = datetime.strptime(day_dir.name.split("=")[1], "%Y-%m-%d").date()

    # Load trades
    trade_files = sorted((day_dir / "trade").glob("*.parquet"))
    if not trade_files:
        return None
    trades = pd.concat([pd.read_parquet(f) for f in trade_files], ignore_index=True)
    if trades.empty:
        return None

    n_total = len(trades)

    # Filter: single-leg electronic only (Dong AEA 2026)
    trades = trades[trades["condition"].isin([0, 18])].copy()
    if trades.empty:
        return None

    # Load quotes to get mid at each 1-min bar per contract
    quote_files = sorted((day_dir / "quote").glob("*.parquet"))
    if not quote_files:
        return None
    quotes = pd.concat([pd.read_parquet(f) for f in quote_files], ignore_index=True)
    if quotes.empty:
        return None

    # Build per-(strike, right, 1-min) mid lookup
    quotes["min_bucket"] = quotes["timestamp"].str[:16]
    quotes["mid"] = (quotes["bid"] + quotes["ask"]) / 2
    # Only use quotes with real 2-sided prices
    quotes = quotes[(quotes["bid"] > 0) & (quotes["ask"] > 0)]
    quote_mid = (
        quotes.groupby(["strike", "right", "min_bucket"])["mid"]
        .last()
        .reset_index()
    )

    # Join trades to quote mid on (strike, right, minute_bucket)
    trades["min_bucket"] = trades["timestamp"].str[:16]
    merged = trades.merge(
        quote_mid,
        on=["strike", "right", "min_bucket"],
        how="left",
    )

    # Classify aggressor via quote rule
    # buy aggressive: trade price > mid
    # sell aggressive: trade price < mid
    # equal: skip (no info)
    merged = merged.dropna(subset=["mid"])
    merged["side"] = 0  # default unknown
    merged.loc[merged["price"] > merged["mid"], "side"] = 1  # buy
    merged.loc[merged["price"] < merged["mid"], "side"] = -1  # sell

    # OPRA-flagged aggressor (condition 145/146) as fallback/override — but we're
    # already filtering to 0/18, so those never appear. Skip.

    merged = merged[merged["side"] != 0].copy()
    n_classified = len(merged)

    # Signed volume per right
    merged["signed_size"] = merged["side"] * merged["size"]
    merged["signed_premium"] = merged["side"] * merged["size"] * merged["price"]

    calls = merged[merged["right"] == "CALL"]
    puts = merged[merged["right"] == "PUT"]

    # Bullish SPX pressure:
    # call BUY = bullish, call SELL = bearish
    # put BUY = bearish, put SELL = bullish
    # So net SPX pressure = (call signed) - (put signed)
    signed_call_vol = calls["signed_size"].sum()
    signed_put_vol = puts["signed_size"].sum()
    signed_net_vol = signed_call_vol - signed_put_vol

    signed_call_prem = calls["signed_premium"].sum()
    signed_put_prem = puts["signed_premium"].sum()
    signed_net_prem = signed_call_prem - signed_put_prem

    return {
        "date": d,
        "signed_call_vol": int(signed_call_vol),
        "signed_put_vol": int(signed_put_vol),
        "signed_net_vol": int(signed_net_vol),
        "signed_call_premium": float(signed_call_prem),
        "signed_put_premium": float(signed_put_prem),
        "signed_net_premium": float(signed_net_prem),
        "n_trades_classified": n_classified,
        "n_trades_total": n_total,
    }


def main():
    day_dirs = sorted(DATA_DIR.glob("date=*"))
    logger.info(f"Computing signed flow across {len(day_dirs)} days...")

    records = []
    for i, dd in enumerate(day_dirs):
        try:
            r = compute_day_flow(dd)
            if r:
                records.append(r)
        except Exception as e:
            logger.warning(f"{dd.name}: {e}")
        if (i + 1) % 50 == 0:
            logger.info(f"  {i+1}/{len(day_dirs)}")

    flow = pd.DataFrame(records)
    flow["date"] = pd.to_datetime(flow["date"])
    flow["year"] = flow["date"].dt.year
    logger.info(f"Computed flow for {len(flow)} days")

    # Load EDA metadata for spot + IV
    meta = pd.read_parquet(EDA_META)
    meta["date"] = pd.to_datetime(meta["date"])

    df = flow.merge(meta[["date", "spot", "atm_iv", "iv_tercile"]], on="date", how="left")
    df = df.sort_values("date").reset_index(drop=True)

    # Next-day spot return (close-to-close proxy using spot field)
    df["next_spot"] = df["spot"].shift(-1)
    df["next_day_ret_pct"] = ((df["next_spot"] - df["spot"]) / df["spot"]) * 100
    df = df.dropna(subset=["next_day_ret_pct"])

    # Z-score signals by year (EDA Implication 3: volume differs 3.5x across years)
    for col in ["signed_net_vol", "signed_net_premium"]:
        df[f"{col}_zyr"] = df.groupby("year")[col].transform(
            lambda x: (x - x.mean()) / x.std()
        )

    # --- Predictions ---
    # Baseline signal: direction of z-score'd net volume
    df["pred_direction_vol"] = np.sign(df["signed_net_vol_zyr"])
    df["pred_direction_prem"] = np.sign(df["signed_net_premium_zyr"])
    df["actual_direction"] = np.sign(df["next_day_ret_pct"])

    # Trading simulation: if pred > threshold, take position
    THRESHOLD = 0.5  # 0.5 std dev above/below yearly mean
    df["signal_vol"] = np.where(
        df["signed_net_vol_zyr"] >= THRESHOLD, 1,
        np.where(df["signed_net_vol_zyr"] <= -THRESHOLD, -1, 0)
    )
    df["trade_return_vol"] = df["signal_vol"] * df["next_day_ret_pct"]
    df["signal_prem"] = np.where(
        df["signed_net_premium_zyr"] >= THRESHOLD, 1,
        np.where(df["signed_net_premium_zyr"] <= -THRESHOLD, -1, 0)
    )
    df["trade_return_prem"] = df["signal_prem"] * df["next_day_ret_pct"]

    # Save
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, compression="zstd")
    logger.info(f"Saved: {OUT_PARQUET}")

    # === Evaluation ===
    def metrics(subset: pd.DataFrame, ret_col: str, sig_col: str) -> dict:
        # Only when signal fires (nonzero)
        trades = subset[subset[sig_col] != 0]
        if trades.empty:
            return {"n": 0}
        rets = trades[ret_col]
        wins = (rets > 0).sum()
        pf_den = -rets[rets < 0].sum()
        pf = rets[rets > 0].sum() / pf_den if pf_den > 0 else float("inf")
        sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
        return {
            "n": len(rets),
            "wr": wins / len(rets) * 100,
            "mean_ret_pct": rets.mean(),
            "total_ret_pct": rets.sum(),
            "sharpe": sharpe,
            "pf": pf,
        }

    # Prediction accuracy (zero-threshold, no trade filter)
    acc_vol = (df["pred_direction_vol"] == df["actual_direction"]).sum() / len(df) * 100
    acc_prem = (df["pred_direction_prem"] == df["actual_direction"]).sum() / len(df) * 100

    # --- Report ---
    out = []
    out.append("# Baseline 1: Signed Flow Predictor — Report\n")
    out.append(f"Generated: {datetime.now().isoformat()}")
    out.append(f"Data: {len(df)} days ({df['date'].min().date()} → {df['date'].max().date()})")
    out.append(f"Filter: single-leg electronic only (condition ∈ {{0, 18}})")
    out.append(f"Aggressor rule: trade price vs 1-min quote mid")
    out.append(f"Signal: net signed flow z-score by year, threshold |z| >= {THRESHOLD}")
    out.append("")

    # Header — predictive power
    out.append("## 1. Direction Prediction Accuracy (sign test)")
    out.append(f"- **Volume-signed**: {acc_vol:.1f}% correct direction ({len(df)} days)")
    out.append(f"- **Premium-signed**: {acc_prem:.1f}% correct direction ({len(df)} days)")
    out.append(f"- (50% = coin flip, need > ~52.5% to be statistically meaningful on this N)")
    out.append("")

    # Overall (signal-filtered) performance
    out.append("## 2. Trade Performance (when |z| >= threshold)")
    all_vol = metrics(df, "trade_return_vol", "signal_vol")
    all_prem = metrics(df, "trade_return_prem", "signal_prem")
    def row(label, m):
        if m["n"] == 0:
            return f"| {label} | 0 | - | - | - | - | - |"
        return f"| {label} | {m['n']} | {m['wr']:.1f}% | {m['mean_ret_pct']:+.3f}% | {m['total_ret_pct']:+.2f}% | {m['sharpe']:.2f} | {m['pf']:.2f} |"
    out.append("| Signal | N | WR | Mean/trade | Total | Sharpe | PF |")
    out.append("|--------|---|-----|-----------|-------|--------|-----|")
    out.append(row("Vol-signed", all_vol))
    out.append(row("Premium-signed", all_prem))
    out.append("")

    # Per year
    out.append("## 3. By Year (vol-signed)")
    out.append("| Year | N | WR | Mean/trade | Total | Sharpe | PF |")
    out.append("|------|---|-----|-----------|-------|--------|-----|")
    for y, sub in df.groupby("year"):
        m = metrics(sub, "trade_return_vol", "signal_vol")
        out.append(row(str(y), m))
    out.append("")

    # Per IV tercile (regime)
    out.append("## 4. By IV Regime (vol-signed)")
    out.append("| Regime | N | WR | Mean/trade | Total | Sharpe | PF |")
    out.append("|--------|---|-----|-----------|-------|--------|-----|")
    for r in ["low_vol", "mid_vol", "high_vol"]:
        sub = df[df["iv_tercile"] == r]
        m = metrics(sub, "trade_return_vol", "signal_vol")
        out.append(row(r, m))
    out.append("")

    # Sensitivity: exclude tariff shock week
    tariff_dates = ["2025-04-07", "2025-04-08", "2025-04-09", "2025-04-10"]
    df_ex = df[~df["date"].dt.strftime("%Y-%m-%d").isin(tariff_dates)]
    out.append("## 5. Sensitivity: Exclude Tariff Shock 2025-04-07..10")
    out.append(f"(4 days removed, remaining: {len(df_ex)})")
    m_ex = metrics(df_ex, "trade_return_vol", "signal_vol")
    m_all = metrics(df, "trade_return_vol", "signal_vol")
    out.append("| Sample | N | WR | Mean/trade | Total | Sharpe | PF |")
    out.append("|--------|---|-----|-----------|-------|--------|-----|")
    out.append(row("full", m_all))
    out.append(row("excl. tariff", m_ex))
    out.append("")

    # Baseline comparison: unconditional long SPX next-day
    uncond_ret = df["next_day_ret_pct"]
    uncond_sharpe = uncond_ret.mean() / uncond_ret.std() * np.sqrt(252)
    uncond_wr = (uncond_ret > 0).sum() / len(uncond_ret) * 100
    out.append("## 6. Unconditional Baseline (always long SPX)")
    out.append(f"- Mean next-day return: **{uncond_ret.mean():+.3f}%**")
    out.append(f"- WR: **{uncond_wr:.1f}%**")
    out.append(f"- Sharpe: **{uncond_sharpe:.2f}**")
    out.append("")

    # Signal distribution
    out.append("## 7. Signal Distribution")
    out.append(f"- Days signal fires long: **{(df['signal_vol'] == 1).sum()}**")
    out.append(f"- Days signal fires short: **{(df['signal_vol'] == -1).sum()}**")
    out.append(f"- Days no signal: **{(df['signal_vol'] == 0).sum()}**")
    out.append("")

    # Verdict
    out.append("## 8. Verdict")
    edge_prediction = acc_vol - 50
    edge_trade = all_vol.get("mean_ret_pct", 0)
    out.append(f"- Direction accuracy edge over coin flip: **{edge_prediction:+.2f} pp**")
    out.append(f"- Mean trade return (filtered): **{edge_trade:+.3f}%**")
    if edge_prediction > 2 and all_vol.get("sharpe", 0) > 0.5:
        out.append(f"- **VERDICT: Weak but plausible edge. Proceed to bootstrap CI + walk-forward.**")
    elif edge_prediction > 0 and all_vol.get("sharpe", 0) > 0:
        out.append(f"- **VERDICT: Marginal edge. Needs Bonferroni adjustment; likely not actionable as-is.**")
    else:
        out.append(f"- **VERDICT: No edge. Either signed flow is noise OR quote-rule classification is too weak.**")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(out))
    logger.info(f"Report: {REPORT}")
    print("\n".join(out[-20:]))


if __name__ == "__main__":
    main()
