"""Verify Theta Standard subscription permissions."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os, asyncio
from dotenv import load_dotenv
load_dotenv(".env")
asyncio.set_event_loop(asyncio.new_event_loop())

from thetadata import Client
from datetime import date, time

c = Client(email=os.getenv('THETA_USERNAME'), password=os.getenv('THETA_PASSWORD'), dataframe_type='pandas')

def try_endpoint(label, fn):
    print(f"\n=== {label} ===")
    try:
        df = fn()
        print(f"Shape: {df.shape}")
        print(f"Columns: {df.columns.tolist()}")
        print(df.head(3).to_string())
    except Exception as e:
        print(f"ERROR {type(e).__name__}: {str(e)[:250]}")

# Core tests
try_endpoint("option_history_quote 1min", lambda: c.option_history_quote(
    symbol='SPY', expiration=date(2025, 11, 3), date=date(2025, 11, 3),
    interval='60000', strike='685000', right='call',
    start_time=time(9, 30), end_time=time(16, 0),
))
try_endpoint("option_history_greeks_eod", lambda: c.option_history_greeks_eod(
    symbol='SPY', expiration=date(2025, 11, 3),
    start_date=date(2025, 11, 3), end_date=date(2025, 11, 3),
))
try_endpoint("option_history_greeks_implied_volatility 1min", lambda: c.option_history_greeks_implied_volatility(
    symbol='SPY', expiration=date(2025, 11, 3), date=date(2025, 11, 3),
    interval='60000', strike='685000', right='call',
    start_time=time(9, 30), end_time=time(16, 0),
))
try_endpoint("stock_history_ohlc 1min (intraday SPY)", lambda: c.stock_history_ohlc(
    symbol='SPY', interval='60000',
    start_date=date(2025, 11, 3), end_date=date(2025, 11, 3),
    start_time=time(9, 30), end_time=time(16, 0),
))
try_endpoint("option_history_greeks_all 1min (all greeks + IV)", lambda: c.option_history_greeks_all(
    symbol='SPY', expiration=date(2025, 11, 3), date=date(2025, 11, 3),
    interval='60000', strike='685000', right='call',
    start_time=time(9, 30), end_time=time(16, 0),
))
