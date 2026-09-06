"""Collects self-storage unit prices into dashboard/data/units.csv.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from .saving import append_snapshot
from .scraping import scrape_cubesmart, scrape_publicstorage
# The date lives with the record whose field it fills; this is the name for
# it at the top level.
from .unit import CAPTURE_DATE as DAY, Unit

# Every module logs to this one name so that the reject-log handler main()
# attaches catches drops from all of them, not just from this file.
logger = logging.getLogger("scraper")


DEFAULT_OUT = Path("dashboard/data/units.csv")
REJECTS_OUT = Path("rejects.log")  # gitignored; the workflow keeps it as an artifact

CHAINS = {
    "cubesmart": ("https://www.cubesmart.com/north-carolina-self-storage/charlotte-self-storage/",
                  scrape_cubesmart),
    "publicstorage": ("https://www.publicstorage.com/self-storage-nc-charlotte",
                      scrape_publicstorage),
}


def main() -> int:
    """Fetch both chains' unit prices and append today's snapshot."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rejects = logging.FileHandler(REJECTS_OUT, mode="w", encoding="utf-8")
    rejects.setLevel(logging.WARNING)
    rejects.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(rejects)

    units: List[Unit] = []
    failures = 0
    # One chain failing should not lose the other chain's snapshot.
    for chain, (start_url, chain_scraper) in CHAINS.items():
        try:
            units += chain_scraper(start_url)
        except Exception as exc:
            logger.error("%s failed: %s", chain, exc)
            failures += 1

    if not units:
        logger.error("No units collected.")
        return 1

    before, after = append_snapshot(units, DEFAULT_OUT)
    logger.info("%s: %d rows -> %d rows (%d units this run)",
                 DEFAULT_OUT, before, after, len(units))
    return 1 if failures else 0

