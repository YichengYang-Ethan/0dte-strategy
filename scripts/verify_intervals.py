"""Find valid interval format for intraday endpoints."""
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

# Try many interval strings
intervals = [
    '1s', '5s', '10s', '30s', '1m', '5m', '15m', '30m', '1h',
    '1min', '5min', '15min',
    '1000', '5000', '60000', '900000',  # ms
    'OneMinute', 'one_minute', '1min_tick',
]

for ival in intervals:
    try:
        df = c.option_history_quote(
            symbol='SPY', expiration=date(2025, 11, 3), date=date(2025, 11, 3),
            interval=ival, strike='685000', right='call',
            start_time=time(10, 0), end_time=time(10, 10),
        )
        print(f"✅ interval='{ival}' works! Shape={df.shape}")
        if not df.empty:
            print(f"   Columns: {df.columns.tolist()[:10]}")
            break
    except Exception as e:
        msg = str(e)[:120]
        if "Invalid interval" in msg:
            pass  # quiet
        elif "No data found" in msg:
            print(f"⚠️  '{ival}' accepted but no data")
        else:
            print(f"❌ '{ival}' {msg[:80]}")
