"""Download extended historical OI: 2024-01-02 → 2025-05-14 (permanent OOS)."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio, logging
from datetime import date
from dotenv import load_dotenv
load_dotenv(".env")

asyncio.set_event_loop(asyncio.new_event_loop())
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from src.data.historical import get_trading_days, download_day, _get_client

START = date(2024, 1, 2)
END = date(2025, 5, 14)

def main():
    days = get_trading_days(START, END)
    print(f"Extended download: {len(days)} days {days[0]} → {days[-1]}", flush=True)
    client = _get_client()
    out = Path("data/historical/spy")
    success = 0
    for d in days:
        if download_day(client, "SPY", d, out):
            success += 1
    print(f"Extended done: {success}/{len(days)}", flush=True)

if __name__ == "__main__":
    main()
