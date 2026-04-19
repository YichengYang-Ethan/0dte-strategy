"""WebSocket dry-run to verify v3 subscription plumbing.

On a weekend (market closed) this should:
  - Open WebSocket to 127.0.0.1:25520
  - Subscribe to 3 test contracts (quote + trade)
  - Receive STATUS heartbeats (~1/sec)
  - Receive REQ_RESPONSE for each subscription
  - Receive NO trade/quote messages (correct — market closed)

On a trading day during market hours, same code should flood with quote/trade.

Duration: 20 seconds, then summary.
"""
from __future__ import annotations
import asyncio
import json
import logging
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import websockets

from src.data.intraday_recorder import (
    REST_BASE,
    WS_URL,
    Contract,
    list_spxw_0dte_contracts,
    send_subscribe,
    verify_terminal_healthy,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dry_run")

DURATION_SEC = 20
TEST_CONTRACT_COUNT = 3


async def main():
    # Use last Friday (2026-04-17) as the reference date for 0DTE universe
    ref_date = date(2026, 4, 17)

    async with httpx.AsyncClient() as http:
        if not await verify_terminal_healthy(http):
            logger.error("Terminal not healthy, abort")
            return
        contracts = await list_spxw_0dte_contracts(http, ref_date)

    if not contracts:
        logger.error("No contracts returned")
        return

    # Pick 3 ATM-ish contracts (middle of the list by strike, mixed C/P)
    contracts_by_strike = sorted(contracts, key=lambda c: (c.strike_1dc, c.right))
    mid = len(contracts_by_strike) // 2
    test_set = contracts_by_strike[mid - 1 : mid + 2]
    logger.info(f"Testing with {len(test_set)} contracts:")
    for c in test_set:
        logger.info(f"  {c.root} {c.expiration_yyyymmdd} strike=${c.strike_1dc/1000:.0f} {c.right}")

    counts = Counter()
    req_responses = []
    start = datetime.now(timezone.utc)

    async with websockets.connect(WS_URL, ping_interval=30, ping_timeout=10) as ws:
        logger.info(f"Connected to {WS_URL}")

        req_id = 1
        for c in test_set:
            await send_subscribe(ws, req_id, "QUOTE", c)
            req_id += 1
            await send_subscribe(ws, req_id, "TRADE", c)
            req_id += 1
        logger.info(f"Sent {req_id - 1} subscribe messages")

        deadline = asyncio.get_event_loop().time() + DURATION_SEC
        try:
            while asyncio.get_event_loop().time() < deadline:
                timeout = deadline - asyncio.get_event_loop().time()
                if timeout <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                try:
                    msg = json.loads(raw)
                except Exception:
                    counts["parse_error"] += 1
                    continue
                htype = (msg.get("header") or {}).get("type", "unknown")
                counts[htype] += 1
                if htype == "REQ_RESPONSE":
                    req_responses.append(msg)
        finally:
            pass

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info("=" * 60)
    logger.info(f"Dry-run complete in {elapsed:.1f}s. Message counts:")
    for htype, n in counts.most_common():
        logger.info(f"  {htype}: {n}")
    logger.info("")
    logger.info(f"REQ_RESPONSE details ({len(req_responses)}):")
    for r in req_responses[:6]:
        h = r.get("header", {})
        logger.info(f"  type={h.get('type')} status={h.get('status')} id={h.get('id')}")

    # Health verdict
    status_count = counts.get("STATUS", 0)
    req_resp_count = counts.get("REQ_RESPONSE", 0)
    quote_count = counts.get("QUOTE", 0)
    trade_count = counts.get("TRADE", 0)

    logger.info("")
    logger.info("VERDICT:")
    if status_count >= elapsed / 2:
        logger.info(f"  STATUS heartbeat: OK ({status_count} in {elapsed:.0f}s)")
    else:
        logger.warning(f"  STATUS heartbeat: LOW ({status_count} in {elapsed:.0f}s, expected >= {elapsed/2:.0f})")
    if req_resp_count == 6:
        logger.info(f"  REQ_RESPONSE: OK (6 expected, got {req_resp_count})")
    else:
        logger.warning(f"  REQ_RESPONSE: MISMATCH (expected 6, got {req_resp_count})")
    if quote_count + trade_count == 0:
        logger.info(f"  Market data: 0 quotes/trades (expected on weekend)")
    else:
        logger.info(f"  Market data: {quote_count} quotes, {trade_count} trades (intraday or backfill)")


if __name__ == "__main__":
    asyncio.run(main())
