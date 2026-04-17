"""Options data fetching from Theta Data and IBKR."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def fetch_options_chain_ibkr(
    ib,
    underlying: str = "SPY",
    expiry: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch full options chain from IBKR TWS/Gateway.

    Returns DataFrame with: strike, right, expiry, bid, ask, last,
    gamma, delta, vega, theta, vanna, open_interest, volume, iv
    """
    from ib_insync import Stock

    stock = Stock(underlying, "SMART", "USD")
    ib.qualifyContracts(stock)

    if expiry is None:
        expiry = datetime.now().strftime("%Y%m%d")

    chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
    if not chains:
        logger.error("No option chains returned")
        return pd.DataFrame()

    # Find the chain matching our expiry
    chain = next((c for c in chains if c.exchange == "SMART"), chains[0])

    strikes = [s for s in chain.strikes if abs(s - ib.reqTickers(stock)[0].marketPrice()) < 30]

    contracts = []
    for strike in strikes:
        for right in ("C", "P"):
            from ib_insync import Option
            c = Option(underlying, expiry, strike, right, "SMART")
            contracts.append(c)

    qualified = ib.qualifyContracts(*contracts)
    tickers = ib.reqTickers(*qualified)

    rows = []
    for ticker in tickers:
        c = ticker.contract
        greeks = ticker.modelGreeks
        rows.append({
            "strike": c.strike,
            "right": c.right,
            "expiry": c.lastTradeDateOrContractMonth,
            "bid": ticker.bid or 0,
            "ask": ticker.ask or 0,
            "last": ticker.last or 0,
            "volume": ticker.volume or 0,
            "open_interest": 0,  # IB doesn't stream OI real-time
            "gamma": greeks.gamma if greeks else 0,
            "delta": greeks.delta if greeks else 0,
            "vega": greeks.vega if greeks else 0,
            "theta": greeks.theta if greeks else 0,
            "iv": greeks.impliedVol if greeks else 0,
            "vanna": 0,  # Not directly from IB, calculate separately
        })

    return pd.DataFrame(rows)


def fetch_options_chain_theta(
    root: str = "SPY",
    expiry: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch options chain snapshot from Theta Data.
    Requires THETA_USERNAME and THETA_PASSWORD in env.
    """
    try:
        from thetadata import ThetaClient
    except ImportError:
        logger.error("thetadata not installed. Run: pip install thetadata")
        return pd.DataFrame()

    import os
    username = os.getenv("THETA_USERNAME", "")
    password = os.getenv("THETA_PASSWORD", "")

    if not username:
        logger.error("THETA_USERNAME not set")
        return pd.DataFrame()

    client = ThetaClient(username=username, passwd=password)

    if expiry is None:
        expiry = datetime.now().strftime("%Y%m%d")

    rows = []
    with client.connect():
        for right in ("C", "P"):
            try:
                data = client.get_snapshot(root=root, exp=expiry, right=right)
                for item in data:
                    rows.append({
                        "strike": item.get("strike", 0) / 1000,
                        "right": right,
                        "expiry": expiry,
                        "bid": item.get("bid", 0),
                        "ask": item.get("ask", 0),
                        "last": item.get("last", 0),
                        "volume": item.get("volume", 0),
                        "open_interest": item.get("open_interest", 0),
                        "gamma": item.get("gamma", 0),
                        "delta": item.get("delta", 0),
                        "vega": item.get("vega", 0),
                        "theta": item.get("theta", 0),
                        "iv": item.get("implied_vol", 0),
                        "vanna": 0,
                    })
            except Exception as e:
                logger.error(f"Theta Data error for {right}: {e}")

    return pd.DataFrame(rows)
