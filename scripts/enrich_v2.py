"""Run Theta v2 enrichment (official Greeks) across all parquets."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio, logging
from dotenv import load_dotenv
load_dotenv(".env")
asyncio.set_event_loop(asyncio.new_event_loop())
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from src.data.enrich_v2 import enrich_all_v2

if __name__ == "__main__":
    enrich_all_v2("SPY", "data/historical/spy")
