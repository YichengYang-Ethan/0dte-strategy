"""Load Open Interest data from Theta Data (daily batch).

OI is published by exchanges after market close and available next morning.
This module fetches yesterday's EOD OI and merges it with live IBKR quotes.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

OI_CACHE_DIR = Path("data/oi_cache")


def fetch_daily_oi(
    root: str = "SPY",
    date: Optional[str] = None,
    cache: bool = True,
) -> pd.DataFrame:
    """
    Fetch end-of-day Open Interest from Theta Data for all strikes/expiries.

    Args:
        root: underlying symbol
        date: YYYYMMDD format. Defaults to previous trading day.
        cache: if True, cache to disk to avoid re-fetching.

    Returns:
        DataFrame with columns: strike, right, expiry, open_interest
    """
    if date is None:
        yesterday = datetime.now() - timedelta(days=1)
        if yesterday.weekday() == 6:  # Sunday
            yesterday -= timedelta(days=2)
        elif yesterday.weekday() == 5:  # Saturday
            yesterday -= timedelta(days=1)
        date = yesterday.strftime("%Y%m%d")

    OI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = OI_CACHE_DIR / f"{root}_oi_{date}.parquet"

    if cache and cache_path.exists():
        logger.info(f"Loading OI from cache: {cache_path}")
        return pd.read_parquet(cache_path)

    logger.info(f"Fetching OI from Theta Data for {root} on {date}")

    try:
        from thetadata import ThetaClient, OptionReqType
    except ImportError:
        logger.error("thetadata not installed. Run: pip install thetadata")
        return pd.DataFrame()

    username = os.getenv("THETA_USERNAME", "")
    password = os.getenv("THETA_PASSWORD", "")
    if not username:
        logger.error("THETA_USERNAME not set in environment")
        return pd.DataFrame()

    rows = []
    client = ThetaClient(username=username, passwd=password)

    with client.connect():
        expirations = client.get_expirations(root=root)

        for exp in expirations:
            exp_str = exp.strftime("%Y%m%d") if hasattr(exp, "strftime") else str(exp)
            for right in ("C", "P"):
                try:
                    data = client.get_snapshot(
                        root=root, exp=exp_str, right=right,
                    )
                    if data is None:
                        continue

                    for item in data if isinstance(data, list) else [data]:
                        oi = 0
                        if isinstance(item, dict):
                            oi = item.get("open_interest", 0) or 0
                            strike = (item.get("strike", 0) or 0) / 1000
                        else:
                            continue

                        if oi > 0:
                            rows.append({
                                "strike": strike,
                                "right": right,
                                "expiry": exp_str,
                                "open_interest": int(oi),
                            })
                except Exception as e:
                    logger.warning(f"Failed to fetch OI for {root} {exp_str} {right}: {e}")

    df = pd.DataFrame(rows)
    if not df.empty and cache:
        df.to_parquet(cache_path, index=False)
        logger.info(f"Cached {len(df)} OI records to {cache_path}")

    return df


def merge_oi_with_live(
    live_df: pd.DataFrame,
    oi_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge daily OI data into live quotes DataFrame.

    live_df has real-time bid/ask/greeks from IBKR but OI=0.
    oi_df has yesterday's EOD OI from Theta Data.
    """
    if oi_df.empty:
        logger.warning("OI data is empty, GEX calculations will be zero")
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
    logger.info(f"OI merge: {filled}/{total} strikes have OI data ({filled/max(total,1)*100:.0f}%)")

    return merged
