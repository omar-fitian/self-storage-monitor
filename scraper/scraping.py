"""The crawl: which pages each chain needs, in what order, and how fast.

This layer does the I/O and owns the error policy -- one facility failing must
not cost the rest, and a chain that reached its facilities and parsed none of
them has failed. It never looks at markup itself.
"""

from __future__ import annotations

import logging
import time
from typing import List

from .fetching import fetch
from .parsing import (
    parse_cubesmart_facility,
    parse_cubesmart_listing,
    parse_publicstorage_listing,
    parse_publicstorage_store,
)
from .unit import Unit, ValidationError

# Every module logs to this one name so that the reject-log handler main()
# attaches catches drops from all of them, not just from this file.
logger = logging.getLogger("scraper")

# Both chains are polite crawls of a few dozen pages, so one second between
# requests costs a minute and keeps well inside what the sites allow.
REQUEST_DELAY_SECONDS = 1.0


def scrape_cubesmart(market: str) -> List[Unit]:
    """Market page for facility identity, then one page per facility."""
    facilities = parse_cubesmart_listing(fetch(market))
    if not facilities:
        raise ValueError("no facilities found on the CubeSmart market page -- layout change?")

    units = []
    for facility in facilities:
        time.sleep(REQUEST_DELAY_SECONDS)
        try:
            units += parse_cubesmart_facility(fetch(facility["url"]), facility)
        except (ValidationError, ValueError, OSError) as exc:
            logger.warning("Dropped cubesmart facility %s: %s", facility["url"], exc)
    if not units:
        # Every facility page failed. Returning an empty list would leave the
        # run looking successful and commit a day holding only the other chain.
        raise ValueError(f"no units parsed from {len(facilities)} CubeSmart facilities")
    logger.info("Parsed %d units from CubeSmart", len(units))
    return units


def scrape_publicstorage(market: str) -> List[Unit]:
    """Market page for store URLs, then one page per store."""
    urls = parse_publicstorage_listing(fetch(market))
    if not urls:
        raise ValueError("no stores found on the Public Storage market page -- layout change?")

    units = []
    for url in urls:
        time.sleep(REQUEST_DELAY_SECONDS)
        try:
            units += parse_publicstorage_store(fetch(url))
        except (ValidationError, ValueError, OSError) as exc:
            logger.warning("Dropped publicstorage store %s: %s", url, exc)
    if not units:
        raise ValueError(f"no units parsed from {len(urls)} Public Storage stores")
    logger.info("Parsed %d units from Public Storage", len(units))
    return units
