"""Intraday SPXW 0DTE recorder — MVP scope.

Night 1 deliverable per GPT_PRO_ROUND5_VERDICT.md:
  1. Verify Theta Terminal running + healthy
  2. List SPXW 0DTE contracts via REST
  3. Connect single WebSocket ws://127.0.0.1:25520/v1/events
  4. Subscribe contract-by-contract (quote + trade) with incrementing req_id
  5. Parse only STATUS / REQ_RESPONSE / QUOTE / TRADE
  6. Write 5-sec microbatches to parquet (zstd)
  7. Log metrics every 10 sec
  8. On disconnect: reconnect, resubscribe from registry, log gap
  9. Night 1 success = 30 min clean, non-trivial parquet, sane rows

Out of scope for Night 1:
  - Recomputed Greeks (use REST later)
  - Feature engineering (M2)
  - Historical backfill (separate job)
  - Multi-day rollover
  - Holiday calendar (Week 2)
  - Full trade stream (confusing; use per-contract)
  - 1-3DTE live (Day 2 expansion after 0DTE verified clean)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

try:
    import httpx
    import websockets
except ImportError as exc:
    raise ImportError(
        "Install deps: pip install httpx websockets pyarrow"
    ) from exc

from src.data.condition_codes import (
    classify,
    is_cancel,
    is_single_leg_electronic,
    is_late_or_oos,
    is_auction,
    is_cross,
    is_complex,
    is_floor,
    is_sweep,
    aggressor_side,
)
from src.data.schema_v1 import SCHEMAS

logger = logging.getLogger(__name__)

# Terminal endpoints (Theta Terminal v3, build >= 20260327).
# v3 changed ports (25510→25503), URL base (/v2→/v3), and param (root→symbol).
REST_BASE = os.getenv("THETA_REST_BASE", "http://127.0.0.1:25503/v3")
WS_URL = os.getenv("THETA_WS_URL", "ws://127.0.0.1:25520/v1/events")
# No dedicated system/status endpoint in v3; healthcheck uses a light list endpoint
TERMINAL_STATUS_URL = os.getenv(
    "THETA_TERMINAL_STATUS", "http://127.0.0.1:25503/v3/option/list/symbols"
)

# Recorder config
FLUSH_INTERVAL_SEC = 7.0              # microbatch target
FLUSH_ROW_THRESHOLD = 50_000          # flush earlier if buffer fills
METRICS_INTERVAL_SEC = 10.0
HEARTBEAT_TIMEOUT_SEC = 15.0          # Terminal sends STATUS every second
MAX_SUBSCRIPTIONS = 10_000            # kill switch before 15k cap
DATA_DIR = Path(os.getenv("RECORDER_DATA_DIR", "data/intraday"))


@dataclass
class Contract:
    root: str
    expiration_yyyymmdd: int
    strike_1dc: int          # 1/10 cent
    right: str               # C | P

    def as_sub_payload(self) -> dict[str, Any]:
        """Build Theta Terminal websocket contract block."""
        return {
            "root": self.root,
            "expiration": self.expiration_yyyymmdd,
            "strike": self.strike_1dc,
            "right": self.right,
        }


@dataclass
class Metrics:
    quotes: int = 0
    trades: int = 0
    status_msgs: int = 0
    req_responses: int = 0
    errors: int = 0
    reconnects: int = 0
    last_heartbeat: float = 0.0
    last_metrics_log: float = 0.0
    buffer_flushes: int = 0
    rows_written: int = 0

    def should_log(self) -> bool:
        now = time.monotonic()
        if now - self.last_metrics_log > METRICS_INTERVAL_SEC:
            self.last_metrics_log = now
            return True
        return False


# -----------------------------------------------------------------------------
# Terminal health check
# -----------------------------------------------------------------------------

async def verify_terminal_healthy(client: httpx.AsyncClient) -> bool:
    """Ping a known-light v3 endpoint. v3 has no dedicated system/status.

    option/list/symbols returns a large CSV; we only care that HTTP 200
    comes back (indicates Terminal loaded subscription + is serving).
    """
    try:
        r = await client.get(TERMINAL_STATUS_URL, timeout=10.0)
        if r.status_code != 200:
            logger.error(f"Terminal healthcheck HTTP {r.status_code}: {r.text[:200]}")
            return False
        # Response is CSV starting with 'symbol\n"..."...'
        if not r.text.startswith("symbol"):
            logger.error(f"Unexpected healthcheck body: {r.text[:200]}")
            return False
        logger.info(f"Terminal healthy (listing {len(r.text.splitlines()) - 1} symbols)")
        return True
    except Exception as e:
        logger.error(f"Terminal healthcheck failed: {e}")
        return False


# -----------------------------------------------------------------------------
# Contract enumeration via REST
# -----------------------------------------------------------------------------

async def list_spxw_0dte_contracts(
    client: httpx.AsyncClient, session_date: date
) -> list[Contract]:
    """Enumerate active SPXW contracts expiring on session_date.

    v3 API: /option/list/contracts/{request_type}?symbol=SPXW&date=YYYYMMDD
    Returns CSV: symbol,expiration,strike,right
    """
    import csv
    import io

    date_str = session_date.strftime("%Y%m%d")
    url = f"{REST_BASE}/option/list/contracts/quote"
    params = {"symbol": "SPXW", "date": date_str}

    try:
        r = await client.get(url, params=params, timeout=30.0)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"list_contracts failed: {e}")
        return []

    reader = csv.DictReader(io.StringIO(r.text))
    contracts: list[Contract] = []
    target_exp = f"{session_date.year}-{session_date.month:02d}-{session_date.day:02d}"
    for row in reader:
        exp_iso = row.get("expiration", "")
        if exp_iso != target_exp:
            continue  # filter: only same-day (0DTE)
        try:
            strike_dollars = float(row["strike"])
            right_word = row["right"].strip().upper()
            right_code = "C" if right_word.startswith("C") else "P"
            contracts.append(Contract(
                root="SPXW",
                expiration_yyyymmdd=int(date_str),
                strike_1dc=int(round(strike_dollars * 1000)),
                right=right_code,
            ))
        except (KeyError, ValueError):
            continue

    logger.info(f"SPXW 0DTE contracts for {date_str}: {len(contracts)}")
    return contracts


# -----------------------------------------------------------------------------
# Message normalization
# -----------------------------------------------------------------------------

def _ts_from_stream(date_yyyymmdd: int, ms_of_day: int) -> datetime:
    """Stream uses date + ms_of_day (local ET). Normalize to UTC.

    Theta stream times are in Eastern Time per docs. For correctness across DST,
    use zoneinfo rather than fixed -05:00.
    """
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    y = date_yyyymmdd // 10000
    m = (date_yyyymmdd // 100) % 100
    d = date_yyyymmdd % 100
    secs = ms_of_day // 1000
    ms = ms_of_day % 1000
    dt_et = datetime(y, m, d, secs // 3600, (secs // 60) % 60, secs % 60, ms * 1000, tzinfo=et)
    return dt_et.astimezone(timezone.utc)


def normalize_quote(msg: dict[str, Any]) -> dict[str, Any]:
    contract = msg.get("contract", {})
    q = msg.get("quote", {})
    date_raw = int(q.get("date", 0))
    ms_raw = int(q.get("ms_of_day", 0))
    ts_utc = _ts_from_stream(date_raw, ms_raw) if date_raw else datetime.now(timezone.utc)

    bid = float(q.get("bid", 0.0))
    ask = float(q.get("ask", 0.0))
    mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else 0.0
    spread = ask - bid if (bid > 0 and ask > 0) else 0.0
    spread_pct = (spread / mid) if mid > 0 else 0.0

    strike_1dc = int(contract.get("strike", 0))
    exp = int(contract.get("expiration", 0))

    return {
        "source_mode": "stream",
        "event_type": "quote",
        "feed_family": "opra",
        "root": str(contract.get("root", "")),
        "underlying_symbol": "SPX",
        "settlement_style": "PM",
        "expiration_yyyymmdd": exp,
        "expiration_date": date(exp // 10000, (exp // 100) % 100, exp % 100) if exp else None,
        "strike_1dc": strike_1dc,
        "strike": strike_1dc / 1000.0,
        "right": str(contract.get("right", "")),

        "event_ts_utc": ts_utc,
        "source_timestamp_text": None,
        "raw_date_yyyymmdd": date_raw,
        "ms_of_day": ms_raw,
        "ingest_ts_utc": datetime.now(timezone.utc),
        "header_type": str(msg.get("header", {}).get("type", "")),
        "header_status": str(msg.get("header", {}).get("status", "")),

        "bid_size": int(q.get("bid_size", 0)),
        "bid_exchange": int(q.get("bid_exchange", 0)),
        "bid": bid,
        "bid_condition": int(q.get("bid_condition", 0)),
        "ask_size": int(q.get("ask_size", 0)),
        "ask_exchange": int(q.get("ask_exchange", 0)),
        "ask": ask,
        "ask_condition": int(q.get("ask_condition", 0)),

        "mid": mid,
        "spread": spread,
        "spread_pct": spread_pct,
    }


def normalize_trade(msg: dict[str, Any]) -> dict[str, Any]:
    contract = msg.get("contract", {})
    t = msg.get("trade", {})
    date_raw = int(t.get("date", 0))
    ms_raw = int(t.get("ms_of_day", 0))
    ts_utc = _ts_from_stream(date_raw, ms_raw) if date_raw else datetime.now(timezone.utc)

    cond = int(t.get("condition", 0))
    strike_1dc = int(contract.get("strike", 0))
    exp = int(contract.get("expiration", 0))

    return {
        "source_mode": "stream",
        "event_type": "trade",
        "feed_family": "opra",
        "root": str(contract.get("root", "")),
        "underlying_symbol": "SPX",
        "settlement_style": "PM",
        "expiration_yyyymmdd": exp,
        "expiration_date": date(exp // 10000, (exp // 100) % 100, exp % 100) if exp else None,
        "strike_1dc": strike_1dc,
        "strike": strike_1dc / 1000.0,
        "right": str(contract.get("right", "")),

        "event_ts_utc": ts_utc,
        "source_timestamp_text": None,
        "raw_date_yyyymmdd": date_raw,
        "ms_of_day": ms_raw,
        "ingest_ts_utc": datetime.now(timezone.utc),
        "header_type": str(msg.get("header", {}).get("type", "")),
        "header_status": str(msg.get("header", {}).get("status", "")),

        "sequence": int(t.get("sequence", 0)),
        "size": int(t.get("size", 0)),
        "condition": cond,
        "exchange": int(t.get("exchange", 0)),
        "price": float(t.get("price", 0.0)),

        "ext_condition1": None,
        "ext_condition2": None,
        "ext_condition3": None,
        "ext_condition4": None,

        "condition_bucket": classify(cond),
        "is_cancel": is_cancel(cond),
        "is_late_or_oos": is_late_or_oos(cond),
        "is_auction": is_auction(cond),
        "is_cross": is_cross(cond),
        "is_complex": is_complex(cond),
        "is_floor": is_floor(cond),
        "is_sweep": is_sweep(cond),
        "is_single_leg_electronic": is_single_leg_electronic(cond),
        "aggressor_side": aggressor_side(cond),
        "is_extended_hours": cond == 148,
    }


# -----------------------------------------------------------------------------
# Parquet microbatch writer
# -----------------------------------------------------------------------------

@dataclass
class ParquetBuffer:
    dataset: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    last_flush: float = field(default_factory=time.monotonic)

    def append(self, row: dict[str, Any]) -> None:
        self.rows.append(row)

    def should_flush(self) -> bool:
        if len(self.rows) >= FLUSH_ROW_THRESHOLD:
            return True
        if time.monotonic() - self.last_flush >= FLUSH_INTERVAL_SEC:
            return len(self.rows) > 0
        return False

    def flush(self) -> int:
        if not self.rows:
            return 0
        n = len(self.rows)
        schema = SCHEMAS[self.dataset]

        # Build partition path from first row's event_ts_utc
        first = self.rows[0]
        ts: datetime = first.get("event_ts_utc") or datetime.now(timezone.utc)
        root = first.get("root", "UNKNOWN")
        part_dir = DATA_DIR / self.dataset / f"root={root}" / f"date={ts.strftime('%Y-%m-%d')}" / f"hour={ts.strftime('%H')}"
        part_dir.mkdir(parents=True, exist_ok=True)
        fname = part_dir / f"part-{int(time.time() * 1000)}.parquet"

        table = pa.Table.from_pylist(self.rows, schema=schema)
        pq.write_table(table, fname, compression="zstd")

        self.rows.clear()
        self.last_flush = time.monotonic()
        return n


# -----------------------------------------------------------------------------
# Recorder main loop
# -----------------------------------------------------------------------------

async def send_subscribe(ws, req_id: int, req_type: str, contract: Contract) -> None:
    payload = {
        "msg_type": "STREAM",
        "sec_type": "OPTION",
        "req_type": req_type,
        "add": True,
        "id": req_id,
        "contract": contract.as_sub_payload(),
    }
    await ws.send(json.dumps(payload))


async def recorder(session_date: date) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient() as http:
        if not await verify_terminal_healthy(http):
            logger.error("Theta Terminal not healthy; abort")
            return

        contracts = await list_spxw_0dte_contracts(http, session_date)
        if not contracts:
            logger.error("No SPXW 0DTE contracts; abort")
            return
        if len(contracts) * 2 > MAX_SUBSCRIPTIONS:
            logger.warning(
                f"Contract count {len(contracts)} × 2 subs exceeds safety cap; "
                f"narrow universe or raise MAX_SUBSCRIPTIONS"
            )
            return

    quote_buf = ParquetBuffer("option_quote")
    trade_buf = ParquetBuffer("option_trade")
    metrics = Metrics()
    metrics.last_heartbeat = time.monotonic()

    sub_registry: list[tuple[str, Contract]] = []
    req_id_counter = 1

    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=30, ping_timeout=10) as ws:
                logger.info(f"Connected to {WS_URL}")

                # Subscribe quote + trade per contract
                sub_registry.clear()
                for c in contracts:
                    await send_subscribe(ws, req_id_counter, "QUOTE", c)
                    sub_registry.append(("QUOTE", c))
                    req_id_counter += 1
                    await send_subscribe(ws, req_id_counter, "TRADE", c)
                    sub_registry.append(("TRADE", c))
                    req_id_counter += 1
                logger.info(f"Subscribed: {len(sub_registry)} streams")

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        metrics.errors += 1
                        continue

                    htype = (msg.get("header") or {}).get("type", "")

                    if htype == "STATUS":
                        metrics.status_msgs += 1
                        metrics.last_heartbeat = time.monotonic()
                    elif htype == "REQ_RESPONSE":
                        metrics.req_responses += 1
                        if msg.get("header", {}).get("status", "").upper() != "CONNECTED":
                            logger.warning(f"REQ_RESPONSE non-ok: {msg}")
                    elif htype == "QUOTE":
                        quote_buf.append(normalize_quote(msg))
                        metrics.quotes += 1
                    elif htype == "TRADE":
                        trade_buf.append(normalize_trade(msg))
                        metrics.trades += 1

                    if quote_buf.should_flush():
                        n = quote_buf.flush()
                        metrics.buffer_flushes += 1
                        metrics.rows_written += n
                    if trade_buf.should_flush():
                        n = trade_buf.flush()
                        metrics.buffer_flushes += 1
                        metrics.rows_written += n

                    if metrics.should_log():
                        logger.info(
                            f"quotes={metrics.quotes} trades={metrics.trades} "
                            f"status={metrics.status_msgs} errors={metrics.errors} "
                            f"reconnects={metrics.reconnects} "
                            f"flushed_rows={metrics.rows_written} "
                            f"hb_age={time.monotonic() - metrics.last_heartbeat:.1f}s"
                        )

                    if time.monotonic() - metrics.last_heartbeat > HEARTBEAT_TIMEOUT_SEC:
                        logger.warning("Heartbeat lost, reconnecting")
                        break

        except Exception as e:
            logger.error(f"WebSocket error: {e}, reconnecting in 2s")
            metrics.reconnects += 1
            # Final flush before reconnect (don't lose buffered data)
            if quote_buf.rows:
                quote_buf.flush()
            if trade_buf.rows:
                trade_buf.flush()
            await asyncio.sleep(2.0)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="Session date YYYY-MM-DD (default: today)")
    args = ap.parse_args()

    session = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date else date.today()
    )

    asyncio.run(recorder(session))


if __name__ == "__main__":
    main()
