"""Enrich existing OI parquets with real Theta Data EOD quotes + computed IV.

Theta Data Value plan includes: option_history_open_interest, option_history_eod,
stock_history_eod. It does NOT include Greeks endpoints. So we compute IV ourselves
from real mid-prices via Newton's method on Black-Scholes.

Usage:
    python -m src.data.enrich --symbol SPY --data-dir data/historical/spy
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from scipy.stats import norm
from scipy.optimize import brentq

logger = logging.getLogger(__name__)


def _ensure_event_loop():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _get_client():
    from thetadata import Client
    return Client(
        email=os.getenv("THETA_USERNAME", ""),
        password=os.getenv("THETA_PASSWORD", ""),
        dataframe_type="pandas",
    )


def bsm_price(S: float, K: float, T: float, r: float, sigma: float, is_call: bool) -> float:
    import math
    if T <= 0 or sigma <= 0:
        intrinsic = max(S - K, 0) if is_call else max(K - S, 0)
        return intrinsic
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if is_call:
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def implied_vol(
    mid: float, S: float, K: float, T: float, r: float, is_call: bool,
) -> float:
    """Solve BSM for IV. Returns 0 if no solution (e.g., price below intrinsic)."""
    if mid <= 0 or T <= 0 or S <= 0 or K <= 0:
        return 0.0
    intrinsic = max(S - K, 0) if is_call else max(K - S, 0)
    if mid < intrinsic * 0.98:
        return 0.0
    try:
        f = lambda sig: bsm_price(S, K, T, r, sig, is_call) - mid
        lo = f(0.01)
        hi = f(3.0)
        if lo * hi > 0:
            return 0.0
        return brentq(f, 0.01, 3.0, xtol=1e-4, maxiter=50)
    except Exception:
        return 0.0


def enrich_day(
    client,
    symbol: str,
    trade_date: date,
    parquet_path: Path,
    r: float = 0.05,
) -> bool:
    """Enrich a single day's parquet with real quotes + computed IV."""
    if not parquet_path.exists():
        logger.warning(f"Skip (missing): {parquet_path}")
        return False

    df = pd.read_parquet(parquet_path)
    if df.empty:
        return False

    if "spot" in df.columns and df["iv"].std() > 0.001:
        logger.debug(f"Already enriched: {parquet_path.name}")
        return True

    # 1. Fetch real SPY spot
    try:
        stock_df = client.stock_history_eod(
            symbol=symbol, start_date=trade_date, end_date=trade_date,
        )
        if stock_df is None or stock_df.empty:
            logger.warning(f"No spot data for {trade_date}")
            return False
        spot = float(stock_df["close"].iloc[0])
    except Exception as e:
        logger.error(f"Spot fetch failed for {trade_date}: {e}")
        return False

    # 2. For each unique expiration, fetch EOD option quotes (both sides)
    expirations = sorted(df["expiry"].unique())
    quote_rows = []
    for exp_str in expirations:
        try:
            exp_date = datetime.strptime(str(exp_str), "%Y%m%d").date()
        except ValueError:
            continue
        try:
            q_df = client.option_history_eod(
                start_date=trade_date, end_date=trade_date,
                symbol=symbol, expiration=exp_date,
            )
            if q_df is None or q_df.empty:
                continue
            for _, row in q_df.iterrows():
                right_raw = str(row.get("right", ""))
                right = "C" if right_raw.upper().startswith("C") else "P"
                quote_rows.append({
                    "strike": float(row["strike"]),
                    "right": right,
                    "expiry": exp_str,
                    "bid": float(row.get("bid", 0) or 0),
                    "ask": float(row.get("ask", 0) or 0),
                    "close": float(row.get("close", 0) or 0),
                    "volume": int(row.get("volume", 0) or 0),
                })
            time.sleep(0.15)
        except Exception as e:
            logger.warning(f"Quote fetch failed {exp_date}: {e}")
            time.sleep(0.5)

    if not quote_rows:
        logger.warning(f"No quotes for {trade_date}")
        return False

    q_df = pd.DataFrame(quote_rows)

    # 3. Merge: keep existing OI from df, replace bid/ask/volume with real data
    df = df.drop(columns=[c for c in ["bid", "ask", "volume", "close"] if c in df.columns])
    merged = df.merge(
        q_df, on=["strike", "right", "expiry"], how="left",
    )

    for col in ["bid", "ask", "close", "volume"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)

    # 4. Compute IV per row using Newton via brentq on real mid prices
    merged["spot"] = spot

    def _iv_row(row):
        bid = row["bid"]
        ask = row["ask"]
        if bid <= 0 or ask <= 0 or ask < bid:
            return 0.0
        mid = (bid + ask) / 2
        try:
            exp = datetime.strptime(str(row["expiry"]), "%Y%m%d").replace(hour=16)
            now = datetime.combine(trade_date, datetime.min.time()).replace(hour=9, minute=30)
            T_seconds = (exp - now).total_seconds()
            T = max(T_seconds / (365 * 24 * 3600), 1 / (365 * 24 * 60))
        except Exception:
            T = 1 / 365
        is_call = row["right"] == "C"
        return implied_vol(mid, spot, float(row["strike"]), T, r, is_call)

    merged["iv"] = merged.apply(_iv_row, axis=1)

    # 5. Overwrite parquet
    merged.to_parquet(parquet_path, index=False)
    n_quotes = (merged["bid"] > 0).sum()
    n_iv = (merged["iv"] > 0).sum()
    logger.info(
        f"Enriched {parquet_path.name}: spot=${spot:.2f} "
        f"quotes={n_quotes}/{len(merged)} iv={n_iv}/{len(merged)}"
    )
    return True


def enrich_all(
    symbol: str = "SPY",
    data_dir: str = "data/historical/spy",
) -> int:
    _ensure_event_loop()
    client = _get_client()
    dir_path = Path(data_dir)
    files = sorted(dir_path.glob("*.parquet"))
    logger.info(f"Enriching {len(files)} files from {dir_path}")

    success = 0
    for fpath in files:
        try:
            d = datetime.strptime(fpath.stem, "%Y%m%d").date()
        except ValueError:
            continue
        if enrich_day(client, symbol, d, fpath):
            success += 1
        time.sleep(0.2)

    logger.info(f"Enriched {success}/{len(files)} days")
    return success


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--data-dir", default="data/historical/spy")
    args = parser.parse_args()

    n = enrich_all(args.symbol, args.data_dir)
    print(f"Done: {n} files enriched")
