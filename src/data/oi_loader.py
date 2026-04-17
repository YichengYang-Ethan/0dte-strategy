"""Load Open Interest data from Theta Data (daily batch).

OI is published by exchanges after market close and available next morning.
This module fetches yesterday's EOD OI and merges it with live IBKR quotes.

Uses thetadata v1.0+ API (Client class, not legacy ThetaClient).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

OI_CACHE_DIR = Path("data/oi_cache")


def _ensure_event_loop():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _get_client():
    """Create Theta Data client from env vars."""
    try:
        from thetadata import Client
    except ImportError:
        logger.error("thetadata not installed. Run: pip3 install thetadata")
        return None

    email = os.getenv("THETA_USERNAME", "")
    password = os.getenv("THETA_PASSWORD", "")
    if not email:
        logger.error("THETA_USERNAME not set")
        return None

    return Client(email=email, password=password, dataframe_type="pandas")


def fetch_expirations(symbol: str = "SPY") -> list[date]:
    """Get all available expiration dates for a symbol."""
    _ensure_event_loop()
    client = _get_client()
    if client is None:
        return []

    df = client.option_list_expirations(symbol=[symbol])
    df["expiration"] = pd.to_datetime(df["expiration"])
    future = df[df["expiration"] >= pd.Timestamp.now()]
    return [row.date() for row in future["expiration"]]


def fetch_daily_oi(
    symbol: str = "SPY",
    expiration: Optional[date] = None,
    cache: bool = True,
) -> pd.DataFrame:
    """
    Fetch Open Interest snapshot from Theta Data for all strikes.

    Args:
        symbol: underlying symbol
        expiration: specific expiry date. If None, fetches nearest expiry.
        cache: cache to disk as parquet

    Returns:
        DataFrame with columns: strike, right, expiry, open_interest
    """
    _ensure_event_loop()
    client = _get_client()
    if client is None:
        return pd.DataFrame()

    OI_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Get nearest expiry if not specified
    if expiration is None:
        exps = fetch_expirations(symbol)
        if not exps:
            logger.error("No expirations found")
            return pd.DataFrame()
        expiration = exps[0]

    exp_str = expiration.strftime("%Y%m%d")
    cache_path = OI_CACHE_DIR / f"{symbol}_oi_{exp_str}.parquet"

    if cache and cache_path.exists():
        logger.info(f"Loading OI from cache: {cache_path}")
        return pd.read_parquet(cache_path)

    logger.info(f"Fetching OI from Theta Data: {symbol} exp={expiration}")

    rows = []
    for right_str, right_label in [("call", "C"), ("put", "P")]:
        try:
            oi_df = client.option_snapshot_open_interest(
                symbol=symbol,
                expiration=expiration,
                right=right_str,
            )
            if oi_df is not None and not oi_df.empty:
                for _, row in oi_df.iterrows():
                    strike = row.get("strike", 0)
                    oi = row.get("open_interest", 0)
                    if strike > 0 and oi > 0:
                        rows.append({
                            "strike": float(strike) / 1000 if strike > 10000 else float(strike),
                            "right": right_label,
                            "expiry": exp_str,
                            "open_interest": int(oi),
                        })
        except Exception as e:
            logger.warning(f"OI fetch error for {symbol} {expiration} {right_str}: {e}")

    df = pd.DataFrame(rows)
    if not df.empty and cache:
        df.to_parquet(cache_path, index=False)
        logger.info(f"Cached {len(df)} OI records to {cache_path}")

    return df


def fetch_all_expiry_oi(
    symbol: str = "SPY",
    max_dte: int = 45,
    cache: bool = True,
) -> pd.DataFrame:
    """Fetch OI for ALL expirations within max_dte days."""
    _ensure_event_loop()
    exps = fetch_expirations(symbol)
    cutoff = date.today() + timedelta(days=max_dte)
    exps = [e for e in exps if e <= cutoff]

    logger.info(f"Fetching OI for {len(exps)} expirations (max {max_dte} DTE)")

    all_dfs = []
    for exp in exps:
        df = fetch_daily_oi(symbol, exp, cache=cache)
        if not df.empty:
            all_dfs.append(df)

    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        logger.info(f"Total OI records: {len(combined)} across {len(all_dfs)} expirations")
        return combined

    return pd.DataFrame()


def merge_oi_with_live(
    live_df: pd.DataFrame,
    oi_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge daily OI into live quotes DataFrame.
    live_df has real-time bid/ask/greeks from IBKR but OI=0.
    oi_df has OI from Theta Data.
    """
    if oi_df.empty:
        logger.warning("OI data empty, GEX will use volume as proxy")
        return live_df

    live = live_df.copy()
    if "open_interest" in live.columns:
        live = live.drop(columns=["open_interest"])

    merged = live.merge(
        oi_df[["strike", "right", "expiry", "open_interest"]],
        on=["strike", "right", "expiry"],
        how="left",
    )
    merged["open_interest"] = merged["open_interest"].fillna(0).astype(int)

    filled = (merged["open_interest"] > 0).sum()
    total = len(merged)
    logger.info(f"OI merge: {filled}/{total} ({filled/max(total,1)*100:.0f}%)")

    return merged
