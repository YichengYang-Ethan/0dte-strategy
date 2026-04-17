"""
0DTE Options Strategy — Main Loop (Production Grade)

GEX/Vanna-driven intraday trading on SPY/SPX 0DTE options.

Usage:
    python main.py                    # Paper trading (default)
    python main.py --live             # Live trading
    python main.py --scan-only        # Print GEX levels only
    python main.py --underlying SPX   # Trade SPX instead of SPY
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime

from dotenv import load_dotenv
from ib_insync import IB, Stock

from src.data.fetcher import fetch_options_chain_ibkr
from src.data.oi_loader import fetch_daily_oi, merge_oi_with_live
from src.gex.calculator import (
    calculate_gex_profile,
    calculate_vanna_exposure,
    identify_levels,
)
from src.gex.greeks import enrich_greeks
from src.signal.generator import generate_signal
from src.execution.trader import ZeroDTETrader, ExitParams
from src.risk.manager import RiskManager, RiskParams

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"logs/0dte_{datetime.now():%Y%m%d}.log"),
    ],
)
logger = logging.getLogger("0dte")

# Ensure log directory exists
os.makedirs("logs", exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description="0DTE GEX/Vanna Strategy")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--underlying", default="SPY")
    parser.add_argument("--interval", type=int, default=300, help="Scan interval seconds")
    args = parser.parse_args()

    paper = not args.live
    if not paper:
        logger.warning("=" * 60)
        logger.warning("LIVE TRADING MODE — REAL MONEY AT RISK")
        logger.warning("=" * 60)
        confirm = input("Type 'CONFIRM LIVE' to proceed: ")
        if confirm != "CONFIRM LIVE":
            logger.info("Aborted.")
            return

    # --- Connect to IB ---
    ib = IB()
    host = os.getenv("IB_HOST", "127.0.0.1")
    port = int(os.getenv("IB_PORT", "4002"))
    client_id = int(os.getenv("IB_CLIENT_ID", "10"))

    logger.info(f"Connecting to IB Gateway {host}:{port} (client {client_id})")
    import asyncio
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    ib.connect(host, port, clientId=client_id)

    # Paper account: use delayed data (free). Live account: use real-time (1).
    if paper:
        ib.reqMarketDataType(3)  # 3 = delayed
    else:
        ib.reqMarketDataType(1)  # 1 = real-time (requires subscription)

    stock = Stock(args.underlying, "SMART", "USD")
    ib.qualifyContracts(stock)
    [ticker] = ib.reqTickers(stock)
    ib.sleep(2)
    spot = ticker.marketPrice()
    logger.info(f"{args.underlying} spot: ${spot:.2f}")

    # --- Load daily OI (once at startup, refresh at 10:00 AM) ---
    logger.info("Loading daily Open Interest from Theta Data...")
    oi_df = fetch_daily_oi(root=args.underlying)
    oi_loaded = not oi_df.empty
    if oi_loaded:
        logger.info(f"Loaded {len(oi_df)} OI records")
    else:
        logger.warning("OI data unavailable — GEX will use volume as proxy (degraded mode)")

    # --- Risk manager ---
    risk = RiskManager(RiskParams(
        max_daily_loss=float(os.getenv("MAX_DAILY_LOSS", "500")),
        max_position_size=int(os.getenv("MAX_POSITION_SIZE", "20")),
        max_premium_per_trade=float(os.getenv("MAX_PREMIUM_PER_TRADE", "200")),
    ))

    # --- Trader ---
    exit_params = ExitParams(
        tp_pct=1.0,
        sl_pct=-0.5,
        trail_activate=0.5,
        trail_pct=0.3,
    )
    trader = ZeroDTETrader(
        ib, risk,
        underlying=args.underlying,
        paper=paper,
        exit_params=exit_params,
    )

    # --- Graceful shutdown ---
    def shutdown(signum, frame):
        logger.info(f"Signal {signum} received, closing all positions...")
        trader.close_all("SIGNAL_SHUTDOWN")
        ib.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    mode_str = "PAPER" if paper else "LIVE"
    logger.info(f"Mode: {mode_str} | Underlying: {args.underlying} | Interval: {args.interval}s")
    logger.info("Entering main loop...")

    last_oi_refresh = datetime.now()

    try:
        while True:
            now = datetime.now()
            h, m = now.hour, now.minute

            # --- Outside market hours ---
            if h < 9 or (h == 9 and m < 30) or h >= 16:
                if h >= 16:
                    trader.close_all("EOD")
                    trader.reconcile_with_ib()
                logger.debug("Outside market hours")
                time.sleep(60)
                continue

            # --- Refresh OI at 10:00 AM (T+1 data becomes available) ---
            if h == 10 and m < 5 and (now - last_oi_refresh).seconds > 3600:
                logger.info("Refreshing daily OI...")
                oi_df = fetch_daily_oi(root=args.underlying, cache=True)
                last_oi_refresh = now

            # --- Get spot ---
            spot = ticker.marketPrice()
            if not spot or spot <= 0:
                logger.warning(f"Invalid spot: {spot}")
                time.sleep(30)
                continue

            # --- Fetch live options chain ---
            logger.info(f"Fetching {args.underlying} options chain (spot=${spot:.2f})...")
            options_df = fetch_options_chain_ibkr(ib, args.underlying)

            if options_df.empty:
                logger.warning("Empty options chain, retry in 60s")
                time.sleep(60)
                continue

            # --- Merge OI from daily batch ---
            if oi_loaded:
                options_df = merge_oi_with_live(options_df, oi_df)

            # --- Compute Vanna + Charm ---
            options_df = enrich_greeks(options_df, spot)

            # --- Calculate GEX ---
            gex_profile = calculate_gex_profile(options_df, spot)
            levels = identify_levels(gex_profile, spot)
            vanna = calculate_vanna_exposure(options_df, spot)

            logger.info(
                f"GEX: {levels.regime} | total={levels.total_gex:,.0f} | "
                f"call_wall={levels.call_wall} | put_wall={levels.put_wall} | "
                f"0-gex={levels.zero_gex} | vanna={vanna.direction} ({vanna.total_vanna:,.0f})"
            )

            if args.scan_only:
                time.sleep(args.interval)
                continue

            # --- Manage existing positions ---
            for pos in trader.positions:
                trader.manage_position(pos)

            # --- Reconcile every 30 minutes ---
            if m % 30 == 0:
                trader.reconcile_with_ib()

            # --- Generate signal ---
            sig = generate_signal(levels, vanna, now)
            logger.info(
                f"Signal: {sig.direction} conf={sig.confidence:.2f} "
                f"session={sig.time_session} | {sig.reason}"
            )

            # --- Execute ---
            if sig.direction != "NEUTRAL" and sig.confidence >= 0.6:
                open_count = sum(1 for p in trader.positions if p.status == "OPEN")
                if open_count == 0:
                    trader.execute(sig, spot, options_df=options_df)
                else:
                    logger.info(f"Already have {open_count} open position(s), skipping")

            time.sleep(args.interval)

    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        trader.close_all("ERROR_SHUTDOWN")
    finally:
        ib.disconnect()
        logger.info("Disconnected from IB")


if __name__ == "__main__":
    main()
