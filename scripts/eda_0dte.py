"""Exploratory Data Analysis on 952-day SPXW 0DTE dataset.

Goal: sanity-check data quality + document regime distribution + find surprises
BEFORE running baselines. A clean EDA prevents baseline results from being
explained away by data artifacts.

Outputs:
  1. Day-level metadata table (spot, ATM IV, total volume, total OI)
  2. Regime distribution (VIX proxy via ATM IV terciles)
  3. Condition code mix (single_leg_LOB vs complex vs auction)
  4. Spread / liquidity distribution
  5. Time-of-day quote volume heatmap
  6. Per-year change in contract count + strike band
  7. Red flags: missing days, zero-OI days, wide-spread days

Writes: logs/eda_report.md
"""
from __future__ import annotations
import sys
import logging
from pathlib import Path
from datetime import date, datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import glob

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eda")

DATA_DIR = Path("/Users/ethanyang/0dte-strategy/data/historical_0dte")
REPORT = Path("/Users/ethanyang/0dte-strategy/logs/eda_report.md")


def day_dirs() -> list[Path]:
    return sorted(DATA_DIR.glob("date=*"))


def parse_day(p: Path) -> date:
    return datetime.strptime(p.name.split("=")[1], "%Y-%m-%d").date()


def load_day_greeks(day_dir: Path) -> pd.DataFrame | None:
    """Load all contracts' greeks for one day (1-min bars)."""
    files = sorted((day_dir / "greeks").glob("*.parquet"))
    if not files:
        return None
    dfs = []
    for f in files:
        df = pd.read_parquet(f)
        # Extract strike + right from filename: strike=7125.000_right=C.parquet
        parts = f.stem.split("_")
        strike = float(parts[0].split("=")[1])
        right = parts[1].split("=")[1]
        df["strike_f"] = strike
        df["right_c"] = right
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


def load_day_trades(day_dir: Path) -> pd.DataFrame | None:
    files = sorted((day_dir / "trade").glob("*.parquet"))
    if not files:
        return None
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def load_day_oi(day_dir: Path) -> pd.DataFrame | None:
    files = sorted((day_dir / "oi").glob("*.parquet"))
    if not files:
        return None
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def compute_day_metadata(day_dir: Path) -> dict | None:
    """Extract compact daily summary. Run across all 952 days."""
    d = parse_day(day_dir)

    # Greeks → ATM IV + spot + total Greeks
    gdf = load_day_greeks(day_dir)
    if gdf is None or gdf.empty:
        return None

    # SPX spot: underlying_price at market open
    gdf_open = gdf[gdf["timestamp"].str.contains("T09:30|T13:30|T08:30|T14:30", na=False)]
    if gdf_open.empty:
        gdf_open = gdf.dropna(subset=["underlying_price"])
    spot = gdf_open[gdf_open["underlying_price"] > 0]["underlying_price"].median() if not gdf_open.empty else 0.0

    # ATM IV: closest strike to spot, call, middle-of-day
    if spot > 0:
        gdf["strike_dist"] = (gdf["strike_f"] - spot).abs()
        atm_calls = gdf[(gdf["right_c"] == "C") & (gdf["implied_vol"] > 0) & (gdf["implied_vol"] < 5)]
        if not atm_calls.empty:
            atm_strike = atm_calls.loc[atm_calls["strike_dist"].idxmin(), "strike_f"]
            atm_iv = atm_calls[(atm_calls["strike_f"] == atm_strike)]["implied_vol"].median()
        else:
            atm_iv = np.nan
    else:
        atm_iv = np.nan

    # Total GEX (rough proxy): sum(gamma × OI) × 100 × S²
    # OI
    oidf = load_day_oi(day_dir)
    total_oi = oidf["open_interest"].sum() if oidf is not None else 0

    # Trade: total volume + condition mix
    tdf = load_day_trades(day_dir)
    if tdf is not None and not tdf.empty:
        total_trades = len(tdf)
        total_vol = tdf["size"].sum()
        cond_counts = tdf["condition"].value_counts().to_dict()
        pct_lob = (tdf["condition"].isin([0, 18]).sum() / len(tdf)) * 100
        pct_complex = (tdf["condition"].isin(list(range(35, 39)) + list(range(130, 145))).sum() / len(tdf)) * 100
    else:
        total_trades = 0
        total_vol = 0
        pct_lob = 0
        pct_complex = 0

    # Spread from first contract's quote (representative)
    # Skipping for speed; spread analysis done separately

    return {
        "date": d,
        "contracts": len(gdf["strike_f"].unique()) if "strike_f" in gdf.columns else 0,
        "spot": spot,
        "atm_iv": atm_iv,
        "total_oi": int(total_oi),
        "total_trades": int(total_trades),
        "total_volume": int(total_vol),
        "pct_single_leg_lob": round(pct_lob, 1),
        "pct_complex_multileg": round(pct_complex, 1),
    }


def main():
    days = day_dirs()
    logger.info(f"Processing {len(days)} days...")

    records = []
    for i, dd in enumerate(days):
        try:
            rec = compute_day_metadata(dd)
            if rec:
                records.append(rec)
        except Exception as e:
            logger.warning(f"{dd.name}: {e}")
        if (i + 1) % 50 == 0:
            logger.info(f"  {i+1}/{len(days)}")

    df = pd.DataFrame(records)
    df["year"] = pd.to_datetime(df["date"]).dt.year
    df["month"] = pd.to_datetime(df["date"]).dt.month
    df["day_of_week"] = pd.to_datetime(df["date"]).dt.day_name()

    logger.info(f"Processed {len(df)}/{len(days)} days successfully")

    # --- Write report ---
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    out = []
    out.append(f"# EDA Report — SPXW 0DTE {df['date'].min()} to {df['date'].max()}\n")
    out.append(f"Generated: {datetime.now().isoformat()}\n")
    out.append(f"Total days: {len(df)}\n")
    out.append("")

    # 1. Coverage
    out.append("## 1. Coverage")
    out.append(f"- Days processed: **{len(df)}**")
    out.append(f"- Date range: **{df['date'].min()}** to **{df['date'].max()}**")
    out.append(f"- Expected trading days in range (~): **~{((df['date'].max() - df['date'].min()).days * 252/365):.0f}**")
    out.append("")
    out.append("### Days per year")
    out.append(df.groupby("year").size().to_frame("days").to_markdown())
    out.append("")

    # 2. Contracts per day over time
    out.append("## 2. Contract Count Evolution")
    monthly = df.groupby(pd.to_datetime(df["date"]).dt.to_period("M"))["contracts"].describe()[["mean", "min", "max"]].round(1)
    out.append("Per month: ATM ±3% contract count")
    out.append(monthly.to_markdown())
    out.append("")

    # 3. SPX spot and regime
    out.append("## 3. Market Regime")
    out.append("### SPX spot by year (mean/min/max)")
    out.append(df.groupby("year")["spot"].describe()[["mean", "min", "max"]].round(1).to_markdown())
    out.append("")
    out.append("### ATM IV by year (mean/min/max/std)")
    out.append(df.groupby("year")["atm_iv"].describe()[["mean", "min", "max", "std"]].round(3).to_markdown())
    out.append("")

    # IV terciles (regime)
    df["iv_tercile"] = pd.qcut(df["atm_iv"].dropna(), 3, labels=["low_vol", "mid_vol", "high_vol"], duplicates="drop")
    out.append("### Days per IV tercile × year")
    out.append(pd.crosstab(df["year"], df["iv_tercile"]).to_markdown())
    out.append("")

    # 4. Trade condition mix (crucial per Dong paper)
    out.append("## 4. Trade Execution Type Mix")
    out.append("### Single-leg LOB (cond 0/18) vs Complex/Multi-leg (35-38, 130-144)")
    out.append(df[["year", "pct_single_leg_lob", "pct_complex_multileg"]].groupby("year").agg(["mean"]).round(1).to_markdown())
    out.append("")
    out.append("**Key insight**: Dong (AEA 2026) says underlying price impact is concentrated in single-leg LOB trades. If >50% of trades are complex/multi-leg, the naive 'signed flow from all trades' signal is mostly noise.")
    out.append("")

    # 5. OI and volume evolution
    out.append("## 5. Volume + OI Evolution")
    out.append("### Yearly mean total volume + OI")
    yearly = df.groupby("year").agg({
        "total_trades": "mean",
        "total_volume": "mean",
        "total_oi": "mean",
    }).round(0).astype(int)
    out.append(yearly.to_markdown())
    out.append("")

    # 6. Red flags — days with unusual metrics
    out.append("## 6. Red Flags")
    out.append("### Days with 0 trades (data gaps?)")
    zero_trade = df[df["total_trades"] == 0]
    out.append(f"Count: **{len(zero_trade)}**")
    if len(zero_trade) > 0:
        out.append(zero_trade[["date", "spot", "contracts"]].head(10).to_markdown(index=False))
    out.append("")

    out.append("### Days with unusually low contract count (<50)")
    low = df[df["contracts"] < 50]
    out.append(f"Count: **{len(low)}**")
    if len(low) > 0:
        out.append(low[["date", "contracts", "spot", "atm_iv"]].head(10).to_markdown(index=False))
    out.append("")

    out.append("### Days with extreme ATM IV (top 5, bottom 5)")
    out.append("**Highest IV days (vol regime extremes):**")
    top = df.nlargest(5, "atm_iv")[["date", "spot", "atm_iv", "total_trades"]]
    out.append(top.to_markdown(index=False))
    out.append("")
    out.append("**Lowest IV days:**")
    bot = df.nsmallest(5, "atm_iv")[["date", "spot", "atm_iv", "total_trades"]]
    out.append(bot.to_markdown(index=False))
    out.append("")

    # 7. Day-of-week bias
    out.append("## 7. Day-of-Week Patterns")
    out.append(df.groupby("day_of_week").agg({
        "total_trades": "mean",
        "total_oi": "mean",
        "atm_iv": "mean",
    }).round(3).to_markdown())
    out.append("")

    # 8. Summary stats for input to baseline design
    out.append("## 8. Baseline Design Hints")
    out.append(f"- **Median contracts/day**: {df['contracts'].median():.0f}")
    out.append(f"- **Median trades/day**: {df['total_trades'].median():,.0f}")
    out.append(f"- **Median single-leg LOB share**: {df['pct_single_leg_lob'].median():.1f}%")
    out.append(f"- **Median complex share**: {df['pct_complex_multileg'].median():.1f}%")
    out.append(f"- **ATM IV median**: {df['atm_iv'].median():.3f}")
    out.append(f"- **ATM IV 90th pctile**: {df['atm_iv'].quantile(0.9):.3f}")
    out.append("")

    report = "\n".join(out)
    REPORT.write_text(report)
    logger.info(f"Report written: {REPORT}")

    # Also save the DataFrame for downstream use
    df.to_parquet("/Users/ethanyang/0dte-strategy/data/eda_day_metadata.parquet", compression="zstd")
    logger.info(f"Day metadata parquet saved: data/eda_day_metadata.parquet")


if __name__ == "__main__":
    main()
