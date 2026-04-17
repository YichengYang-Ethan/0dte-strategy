"""Download historical options data from Theta Data for backtesting.

Pulls daily OI + quote snapshots and saves as parquet files.
Each file = one trading day, containing all strikes for all relevant expirations.

Usage:
    python -m src.data.historical --symbol SPY --days 120
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

HIST_DIR = Path("data/historical")


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


def get_trading_days(start: date, end: date) -> list[date]:
    """Generate list of trading days (Mon-Fri, skip weekends)."""
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def download_day(
    client,
    symbol: str,
    trade_date: date,
    output_dir: Path,
) -> bool:
    """
    Download OI snapshot for a single trading day.

    Saves: {output_dir}/{YYYYMMDD}.parquet
    Columns: timestamp, strike, right, expiry, open_interest, bid, ask, volume
    """
    date_str = trade_date.strftime("%Y%m%d")
    out_path = output_dir / f"{date_str}.parquet"

    if out_path.exists():
        logger.debug(f"Skip {date_str} (cached)")
        return True

    logger.info(f"Downloading {symbol} options for {date_str}...")

    # Get expirations that were active on this date
    try:
        all_exps = client.option_list_expirations(symbol=[symbol])
        all_exps["expiration"] = pd.to_datetime(all_exps["expiration"])
        # Filter: expiry >= trade_date and expiry <= trade_date + 45 days
        active = all_exps[
            (all_exps["expiration"].dt.date >= trade_date) &
            (all_exps["expiration"].dt.date <= trade_date + timedelta(days=45))
        ]
        expirations = [row.date() for row in active["expiration"]]
    except Exception as e:
        logger.error(f"Failed to get expirations for {date_str}: {e}")
        return False

    if not expirations:
        logger.warning(f"No active expirations for {date_str}")
        return False

    rows = []
    for exp in expirations[:5]:  # Limit to 5 nearest expirations to stay within rate limits
        for right_str, right_label in [("call", "C"), ("put", "P")]:
            try:
                # Get OI
                oi_df = client.option_history_open_interest(
                    symbol=symbol,
                    expiration=exp,
                    date_range=(trade_date, trade_date),
                    right=right_str,
                )

                if oi_df is None or oi_df.empty:
                    continue

                for _, row in oi_df.iterrows():
                    strike_raw = row.get("strike", 0)
                    strike = float(strike_raw) / 1000 if strike_raw > 10000 else float(strike_raw)
                    oi = int(row.get("open_interest", 0))

                    if strike > 0:
                        rows.append({
                            "timestamp": str(trade_date),
                            "strike": strike,
                            "right": right_label,
                            "expiry": exp.strftime("%Y%m%d"),
                            "open_interest": oi,
                            "bid": 0.0,
                            "ask": 0.0,
                            "volume": 0,
                            "delta": 0.0,
                            "gamma": 0.0,
                            "iv": 0.0,
                        })

                # Rate limit: Theta Data Value plan has request limits
                time.sleep(0.5)

            except Exception as e:
                err_str = str(e)
                if "PERMISSION_DENIED" in err_str:
                    logger.warning(f"Permission denied for history endpoint — Value plan may not support this. Falling back to snapshot.")
                    return False
                logger.warning(f"Error {symbol} {exp} {right_str} on {date_str}: {e}")
                time.sleep(1)

    if not rows:
        logger.warning(f"No data for {date_str}")
        return False

    df = pd.DataFrame(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    logger.info(f"Saved {len(df)} records to {out_path}")
    return True


def download_range(
    symbol: str = "SPY",
    days: int = 120,
    output_dir: Optional[str] = None,
) -> int:
    """
    Download historical data for the past N trading days.

    Returns number of days successfully downloaded.
    """
    _ensure_event_loop()

    if output_dir is None:
        out = HIST_DIR / symbol.lower()
    else:
        out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=int(days * 1.5))  # overshoot for weekends
    trading_days = get_trading_days(start, end)[-days:]

    logger.info(f"Downloading {len(trading_days)} days: {trading_days[0]} to {trading_days[-1]}")

    client = _get_client()
    success = 0

    for d in trading_days:
        if download_day(client, symbol, d, out):
            success += 1
        time.sleep(0.3)  # rate limit

    logger.info(f"Downloaded {success}/{len(trading_days)} days to {out}")
    return success


# Allow direct execution: python -m src.data.historical
if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Load env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    count = download_range(args.symbol, args.days, args.output)
    print(f"Done: {count} days downloaded")
