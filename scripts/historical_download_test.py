"""Phase A: 1-day historical download verification.

Tests REST v3 historical endpoints end-to-end:
  - option_history_quote (1-min interval)
  - option_history_trade
  - option_history_greeks_all (1-min)
  - option_history_open_interest
  - index_history_price (SPX spot, 1-min)

Target: SPXW 2026-04-17 (Friday, known-good), ATM ±2% strikes only.
Goal: verify field names + storage pipeline + reasonable throughput.
No production storage; writes to /tmp/theta_test_*.csv for inspection.
"""
from __future__ import annotations
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hist")

REST_BASE = "http://127.0.0.1:25503/v3"
TEST_DATE = "20260417"
TEST_EXP = "20260417"   # same-day 0DTE


async def try_endpoint(client: httpx.AsyncClient, name: str, url: str, params: dict) -> None:
    logger.info(f"--- {name} ---")
    try:
        r = await client.get(url, params=params, timeout=30.0)
    except Exception as e:
        logger.error(f"FAILED: {e}")
        return
    logger.info(f"HTTP {r.status_code}, {len(r.text)} bytes")
    if r.status_code != 200:
        logger.error(f"body: {r.text[:300]}")
        return
    lines = r.text.splitlines()
    logger.info(f"rows: {len(lines) - 1} (excluding header)")
    logger.info(f"header: {lines[0] if lines else '(empty)'}")
    for line in lines[1:4]:
        logger.info(f"  {line}")
    if len(lines) > 4:
        logger.info(f"  ... ({len(lines) - 1 - 3} more)")


async def main():
    async with httpx.AsyncClient() as c:
        # 1. Find ATM strike on the test date using snapshot/quote
        #    Actually, easier: just pick 6700 which is near recent SPX levels
        spot_guess = 7125  # SPX approximately on 2026-04-17
        atm_strike_1dc = spot_guess * 1000  # integer in 1/10 cent

        # 2. Test endpoints one at a time
        await try_endpoint(
            c, "option_history_quote (1-min)",
            f"{REST_BASE}/option/history/quote",
            {
                "symbol": "SPXW",
                "expiration": TEST_EXP,
                "strike": str(atm_strike_1dc),
                "right": "call",
                "start_date": TEST_DATE,
                "end_date": TEST_DATE,
                "interval": "60000",  # 1-min
            },
        )

        await try_endpoint(
            c, "option_history_trade (tick)",
            f"{REST_BASE}/option/history/trade",
            {
                "symbol": "SPXW",
                "expiration": TEST_EXP,
                "strike": str(atm_strike_1dc),
                "right": "call",
                "start_date": TEST_DATE,
                "end_date": TEST_DATE,
            },
        )

        await try_endpoint(
            c, "option_history_greeks_all (1-min)",
            f"{REST_BASE}/option/history/greeks/all",
            {
                "symbol": "SPXW",
                "expiration": TEST_EXP,
                "strike": str(atm_strike_1dc),
                "right": "call",
                "start_date": TEST_DATE,
                "end_date": TEST_DATE,
                "interval": "60000",
            },
        )

        await try_endpoint(
            c, "option_history_open_interest",
            f"{REST_BASE}/option/history/open_interest",
            {
                "symbol": "SPXW",
                "expiration": TEST_EXP,
                "strike": str(atm_strike_1dc),
                "right": "call",
                "start_date": TEST_DATE,
                "end_date": TEST_DATE,
            },
        )

        await try_endpoint(
            c, "index_history_price (SPX 1-min)",
            f"{REST_BASE}/index/history/price",
            {
                "symbol": "SPX",
                "start_date": TEST_DATE,
                "end_date": TEST_DATE,
                "interval": "60000",
            },
        )


if __name__ == "__main__":
    asyncio.run(main())
