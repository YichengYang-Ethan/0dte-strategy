"""Economic event calendar for FOMC, CPI, NFP, and options expiration dates.

On event days, GEX predictive power degrades. Vanna flows from IV crush
dominate gamma flows. Strategy should switch to vanna-dominant mode or
reduce position sizes.

Reference: Nomura (McElligott) daily flow notes; Baltussen et al. (2021)
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Hardcoded 2026 FOMC meeting dates (from federalreserve.gov)
# These are the STATEMENT release dates (usually 2:00 PM ET)
FOMC_2026 = [
    date(2026, 1, 28), date(2026, 1, 29),   # Jan meeting
    date(2026, 3, 17), date(2026, 3, 18),   # Mar meeting
    date(2026, 5, 5), date(2026, 5, 6),     # May meeting
    date(2026, 6, 16), date(2026, 6, 17),   # Jun meeting
    date(2026, 7, 28), date(2026, 7, 29),   # Jul meeting
    date(2026, 9, 15), date(2026, 9, 16),   # Sep meeting
    date(2026, 10, 27), date(2026, 10, 28), # Oct meeting
    date(2026, 12, 15), date(2026, 12, 16), # Dec meeting
]

# Monthly options expiration = 3rd Friday of each month
def monthly_opex_dates(year: int) -> list[date]:
    dates = []
    for month in range(1, 13):
        first_day = date(year, month, 1)
        # Find first Friday
        days_until_friday = (4 - first_day.weekday()) % 7
        first_friday = first_day + timedelta(days=days_until_friday)
        third_friday = first_friday + timedelta(weeks=2)
        dates.append(third_friday)
    return dates

# Triple witching = 3rd Friday of Mar, Jun, Sep, Dec
def triple_witching_dates(year: int) -> list[date]:
    opex = monthly_opex_dates(year)
    return [d for d in opex if d.month in (3, 6, 9, 12)]


class EventCalendar:
    def __init__(self, year: int = 2026):
        self.fomc_dates = set(FOMC_2026)
        self.opex_dates = set(monthly_opex_dates(year))
        self.triple_witching = set(triple_witching_dates(year))
        self.cpi_dates: set[date] = set()
        self.nfp_dates: set[date] = set()
        self._loaded_from_api = False

    def load_from_finnhub(self, api_key: Optional[str] = None):
        """Load CPI and NFP dates from Finnhub free API."""
        key = api_key or os.getenv("FINNHUB_API_KEY", "")
        if not key:
            logger.warning("FINNHUB_API_KEY not set, using hardcoded FOMC only")
            return

        try:
            year = datetime.now().year
            url = f"https://finnhub.io/api/v1/calendar/economic"
            params = {
                "from": f"{year}-01-01",
                "to": f"{year}-12-31",
                "token": key,
            }
            resp = httpx.get(url, params=params, timeout=10)
            data = resp.json()

            for event in data.get("economicCalendar", []):
                name = (event.get("event", "") or "").lower()
                impact = event.get("impact", "")
                event_date = event.get("date", "")[:10]

                if not event_date:
                    continue

                try:
                    d = date.fromisoformat(event_date)
                except ValueError:
                    continue

                if "cpi" in name and ("core" in name or "consumer price" in name):
                    self.cpi_dates.add(d)
                elif "nonfarm" in name or "non-farm" in name or "nfp" in name:
                    self.nfp_dates.add(d)

            self._loaded_from_api = True
            logger.info(
                f"Event calendar loaded: {len(self.cpi_dates)} CPI dates, "
                f"{len(self.nfp_dates)} NFP dates"
            )

        except Exception as e:
            logger.warning(f"Failed to load Finnhub calendar: {e}")

    def classify_day(self, d: Optional[date] = None) -> dict:
        """
        Classify a trading day for risk management.

        Returns dict with:
            is_fomc: bool
            is_cpi: bool
            is_nfp: bool
            is_opex: bool
            is_triple_witching: bool
            is_event_day: bool (any major event)
            risk_multiplier: float (0.0 = no trade, 0.5 = half size, 1.0 = normal)
            mode: str ("NORMAL", "VANNA_DOMINANT", "NO_TRADE")
        """
        if d is None:
            d = date.today()

        is_fomc = d in self.fomc_dates
        is_cpi = d in self.cpi_dates
        is_nfp = d in self.nfp_dates
        is_opex = d in self.opex_dates
        is_tw = d in self.triple_witching

        is_event = is_fomc or is_cpi or is_nfp

        if is_fomc:
            # FOMC days: IV crush post-statement drives massive vanna flows
            # Gamma signals become unreliable after 2:00 PM ET
            mode = "VANNA_DOMINANT"
            risk_mult = 0.5
        elif is_cpi or is_nfp:
            # CPI/NFP: pre-market release (8:30 AM ET)
            # First 30 minutes are chaos, then vanna unwinds dominate
            mode = "VANNA_DOMINANT"
            risk_mult = 0.5
        elif is_tw:
            # Triple witching: extreme gamma, pin risk, wide spreads
            mode = "NORMAL"
            risk_mult = 0.7
        elif is_opex:
            # Monthly opex: elevated gamma, some pin risk
            mode = "NORMAL"
            risk_mult = 0.85
        else:
            mode = "NORMAL"
            risk_mult = 1.0

        return {
            "is_fomc": is_fomc,
            "is_cpi": is_cpi,
            "is_nfp": is_nfp,
            "is_opex": is_opex,
            "is_triple_witching": is_tw,
            "is_event_day": is_event,
            "risk_multiplier": risk_mult,
            "mode": mode,
        }
