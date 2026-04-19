"""Historical SPXW 0DTE data downloader (v3 API).

Downloads for a given date range:
  - 1-min quotes (bid/ask/size/condition)
  - tick trades (price/size/condition/exchange)
  - 1-min Greeks (delta/gamma/vanna/charm/IV/underlying_price)
  - Daily OI per contract

Strategy:
  - Enumerate 0DTE SPXW contracts for each trading day
  - Filter to ATM ±band_pct from SPX spot
  - Concurrent fetch (Pro tier allows 8 concurrent requests)
  - Stream each contract's data to parquet, partitioned by date

Usage:
  python scripts/download_historical_0dte.py --start 2026-04-13 --end 2026-04-17 --band-pct 3
"""
from __future__ import annotations
import argparse
import asyncio
import io
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pandas as pd

REST_BASE = "http://127.0.0.1:25503/v3"
CONCURRENCY = 6  # Pro tier allows 8; stay under
DATA_DIR = Path("data/historical_0dte")
logger = logging.getLogger("downloader")


async def list_contracts(client: httpx.AsyncClient, d: date) -> pd.DataFrame:
    """Return all SPXW contracts expiring on date d."""
    date_str = d.strftime("%Y%m%d")
    r = await client.get(
        f"{REST_BASE}/option/list/contracts/quote",
        params={"symbol": "SPXW", "date": date_str},
        timeout=60.0,
    )
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df["expiration"] = pd.to_datetime(df["expiration"]).dt.date
    df = df[df["expiration"] == d]  # 0DTE only
    df["right_code"] = df["right"].str.upper().str[0]
    return df


async def get_spot(client: httpx.AsyncClient, d: date) -> float | None:
    """Approximate SPX spot at open from Greeks endpoint of any 0DTE contract.

    Strategy: pick a strike from the middle of the contract list (likely ATM),
    then query Greeks to read underlying_price.
    """
    date_str = d.strftime("%Y%m%d")
    # First: enumerate strikes available, pick median (likely near ATM)
    try:
        r = await client.get(
            f"{REST_BASE}/option/list/strikes",
            params={"symbol": "SPXW", "expiration": date_str},
            timeout=30.0,
        )
        if r.status_code == 200:
            strikes_df = pd.read_csv(io.StringIO(r.text))
            if not strikes_df.empty:
                strikes = sorted(strikes_df["strike"].unique())
                # Query middle strike first, then neighbors if it fails
                mid = len(strikes) // 2
                order = list(range(mid, len(strikes))) + list(range(mid - 1, -1, -1))
                for idx in order[:10]:
                    strike = strikes[idx]
                    try:
                        gr = await client.get(
                            f"{REST_BASE}/option/history/greeks/all",
                            params={
                                "symbol": "SPXW",
                                "expiration": date_str,
                                "strike": f"{strike:.3f}",
                                "right": "call",
                                "start_date": date_str,
                                "end_date": date_str,
                                "interval": "1m",
                            },
                            timeout=30.0,
                        )
                        if gr.status_code != 200:
                            continue
                        df = pd.read_csv(io.StringIO(gr.text))
                        if df.empty or "underlying_price" not in df.columns:
                            continue
                        # Filter for non-zero underlying
                        nonzero = df[df["underlying_price"] > 0]
                        if not nonzero.empty:
                            return float(nonzero["underlying_price"].iloc[0])
                    except Exception:
                        continue
    except Exception:
        pass
    return None


async def fetch_csv(
    client: httpx.AsyncClient, url: str, params: dict
) -> pd.DataFrame | None:
    try:
        r = await client.get(url, params=params, timeout=60.0)
    except Exception as e:
        logger.warning(f"fetch failed: {e}")
        return None
    if r.status_code != 200:
        logger.debug(f"{url} {params} -> HTTP {r.status_code}: {r.text[:100]}")
        return None
    try:
        return pd.read_csv(io.StringIO(r.text))
    except Exception:
        return None


async def download_contract(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    d: date,
    strike: float,
    right_code: str,
    out_dir: Path,
) -> dict:
    """Download all 4 datasets for one contract on one day."""
    date_str = d.strftime("%Y%m%d")
    strike_str = f"{strike:.3f}"
    right_word = "call" if right_code == "C" else "put"
    base_params = {
        "symbol": "SPXW",
        "expiration": date_str,
        "strike": strike_str,
        "right": right_word,
        "start_date": date_str,
        "end_date": date_str,
    }
    results = {"quote": 0, "trade": 0, "greeks": 0, "oi": 0}

    async with sem:
        # 1-min quote
        df = await fetch_csv(client, f"{REST_BASE}/option/history/quote",
                             {**base_params, "interval": "1m"})
        if df is not None and not df.empty:
            results["quote"] = len(df)
            df.to_parquet(out_dir / "quote" / f"strike={strike_str}_right={right_code}.parquet",
                          compression="zstd", index=False)

        # tick trade
        df = await fetch_csv(client, f"{REST_BASE}/option/history/trade",
                             {**base_params, "interval": "tick"})
        if df is not None and not df.empty:
            results["trade"] = len(df)
            df.to_parquet(out_dir / "trade" / f"strike={strike_str}_right={right_code}.parquet",
                          compression="zstd", index=False)

        # 1-min Greeks
        df = await fetch_csv(client, f"{REST_BASE}/option/history/greeks/all",
                             {**base_params, "interval": "1m"})
        if df is not None and not df.empty:
            results["greeks"] = len(df)
            df.to_parquet(out_dir / "greeks" / f"strike={strike_str}_right={right_code}.parquet",
                          compression="zstd", index=False)

        # OI (no interval)
        df = await fetch_csv(client, f"{REST_BASE}/option/history/open_interest", base_params)
        if df is not None and not df.empty:
            results["oi"] = len(df)
            df.to_parquet(out_dir / "oi" / f"strike={strike_str}_right={right_code}.parquet",
                          compression="zstd", index=False)

    return results


async def download_day(client: httpx.AsyncClient, d: date, band_pct: float) -> dict:
    logger.info(f"=== {d} ===")
    contracts = await list_contracts(client, d)
    logger.info(f"  0DTE contracts total: {len(contracts)}")

    spot = await get_spot(client, d)
    if spot is None:
        logger.error(f"  {d}: cannot determine SPX spot, skip")
        return {"date": d, "contracts": 0, "quote": 0, "trade": 0, "greeks": 0, "oi": 0, "elapsed_sec": 0.0}
    logger.info(f"  SPX spot ~{spot:.2f}")

    band_lo = spot * (1 - band_pct / 100)
    band_hi = spot * (1 + band_pct / 100)
    band_mask = (contracts["strike"] >= band_lo) & (contracts["strike"] <= band_hi)
    universe = contracts[band_mask]
    logger.info(f"  ATM ±{band_pct}% = [{band_lo:.0f}, {band_hi:.0f}]: {len(universe)} contracts")

    out_dir = DATA_DIR / f"date={d.strftime('%Y-%m-%d')}"
    for ds in ["quote", "trade", "greeks", "oi"]:
        (out_dir / ds).mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    t0 = time.time()
    tasks = [
        download_contract(client, sem, d, row["strike"], row["right_code"], out_dir)
        for _, row in universe.iterrows()
    ]
    results = await asyncio.gather(*tasks)
    elapsed = time.time() - t0

    totals = {k: sum(r[k] for r in results) for k in ["quote", "trade", "greeks", "oi"]}
    logger.info(f"  downloaded in {elapsed:.1f}s: quote={totals['quote']} trade={totals['trade']} greeks={totals['greeks']} oi={totals['oi']}")
    return {"date": d, "contracts": len(universe), **totals, "elapsed_sec": elapsed}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--band-pct", type=float, default=3.0, help="strike envelope around spot, percent")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    summary = []

    async with httpx.AsyncClient() as client:
        d = start
        while d <= end:
            if d.weekday() < 5:  # Mon-Fri only
                try:
                    res = await download_day(client, d, args.band_pct)
                    summary.append(res)
                except Exception as e:
                    logger.error(f"  {d}: {e}")
            d += timedelta(days=1)

    logger.info("=" * 60)
    logger.info("SUMMARY")
    df = pd.DataFrame(summary)
    if not df.empty:
        logger.info("\n" + df.to_string(index=False))
        logger.info(f"Total elapsed: {df['elapsed_sec'].sum():.0f}s")
        logger.info(f"Total quote rows: {df['quote'].sum():,}")
        logger.info(f"Total trade rows: {df['trade'].sum():,}")


if __name__ == "__main__":
    asyncio.run(main())
