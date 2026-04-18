"""Enrich OOS OI parquets with real EOD quotes + computed IV."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging, asyncio
from dotenv import load_dotenv
load_dotenv(".env")
asyncio.set_event_loop(asyncio.new_event_loop())
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from src.data.enrich import enrich_all

if __name__ == "__main__":
    enrich_all("SPY", "data/historical/spy")
