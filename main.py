"""
0DTE Options Strategy — Main Loop

GEX/Vanna-driven intraday trading on SPY/SPX 0DTE options.
Connects to IBKR Gateway, calculates GEX profile every N minutes,
generates signals, and executes trades with risk management.

Usage:
    python main.py              # Paper trading mode (default)
    python main.py --live       # Live trading (careful!)
    python main.py --scan-only  # Just print GEX levels, no trading
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime

from dotenv import load_dotenv
from ib_insync import IB

from src.data.fetcher import fetch_options_chain_ibkr
from src.gex.calculator import (
    calculate_gex_profile,
    calculate_vanna_exposure,
    identify_levels,
)
from src.signal.generator import generate_signal
from src.execution.trader import ZeroDTETrader
from src.risk.manager import RiskManager, RiskParams

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("0dte")

SCAN_INTERVAL_SECONDS = 300  # 5 minutes


def main():
    parser = argparse.ArgumentParser(description="0DTE GEX/Vanna Strategy")
    parser.add_argument("--live", action="store_true", help="Live trading mode")
    parser.add_argument("--scan-only", action="store_true", help="Just print GEX levels")
    parser.add_argument("--underlying", default="SPY", help="Underlying symbol")
    parser.add_argument("--interval", type=int, default=300, help="Scan interval in seconds")
    args = parser.parse_args()

    paper = not args.live

    # Connect to IB
    ib = IB()
    host = os.getenv("IB_HOST", "127.0.0.1")
    port = int(os.getenv("IB_PORT", "4002"))
    client_id = int(os.getenv("IB_CLIENT_ID", "1"))

    logger.info(f"Connecting to IB Gateway at {host}:{port} (client {client_id})")
    ib.connect(host, port, clientId=client_id)

    # Get spot price
    from ib_insync import Stock
    stock = Stock(args.underlying, "SMART", "USD")
    ib.qualifyContracts(stock)
    ticker = ib.reqMktData(stock)
    ib.sleep(2)
    spot = ticker.marketPrice()
    logger.info(f"{args.underlying} spot: ${spot:.2f}")

    # Risk manager
    risk = RiskManager(RiskParams(
        max_daily_loss=float(os.getenv("MAX_DAILY_LOSS", "500")),
        max_position_size=int(os.getenv("MAX_POSITION_SIZE", "20")),
        max_premium_per_trade=float(os.getenv("MAX_PREMIUM_PER_TRADE", "200")),
    ))

    # Trader
    trader = ZeroDTETrader(ib, risk, underlying=args.underlying, paper=paper)

    logger.info(f"Mode: {'PAPER' if paper else 'LIVE'} | Scan interval: {args.interval}s")
    logger.info("Starting main loop...")

    try:
        while True:
            now = datetime.now()

            # Market hours check (9:30 AM - 4:00 PM ET)
            if now.hour < 9 or (now.hour == 9 and now.minute < 30) or now.hour >= 16:
                if now.hour >= 16 and trader.positions:
                    trader.close_all("EOD")
                logger.info("Outside market hours. Sleeping 60s...")
                time.sleep(60)
                continue

            # Refresh spot
            spot = ticker.marketPrice()

            # Fetch options chain
            logger.info(f"Fetching options chain for {args.underlying}...")
            options_df = fetch_options_chain_ibkr(ib, args.underlying)

            if options_df.empty:
                logger.warning("Empty options chain, retrying in 60s")
                time.sleep(60)
                continue

            # Calculate GEX
            gex_profile = calculate_gex_profile(options_df, spot)
            levels = identify_levels(gex_profile, spot)
            vanna = calculate_vanna_exposure(options_df, spot)

            logger.info(
                f"GEX: regime={levels.regime} | call_wall={levels.call_wall} | "
                f"put_wall={levels.put_wall} | total={levels.total_gex:.0f} | "
                f"vanna={vanna.direction} ({vanna.total_vanna:.0f})"
            )

            if args.scan_only:
                time.sleep(args.interval)
                continue

            # Manage existing positions
            for pos in trader.positions:
                trader.manage_position(pos)

            # Generate signal
            signal = generate_signal(levels, vanna)
            logger.info(
                f"Signal: {signal.direction} | conf={signal.confidence:.2f} | "
                f"target={signal.target} | reason={signal.reason}"
            )

            # Execute if signal is actionable
            if signal.direction != "NEUTRAL" and signal.confidence >= 0.6:
                open_positions = [p for p in trader.positions if p.status == "OPEN"]
                if not open_positions:
                    trader.execute(signal, spot)

            time.sleep(args.interval)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
        trader.close_all("SHUTDOWN")
    finally:
        ib.disconnect()


if __name__ == "__main__":
    main()
