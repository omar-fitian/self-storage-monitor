"""Writing the day's units into the CSV log.

The log is one row per unit per capture date, and this module owns what makes
a row unique and what a re-run is allowed to overwrite.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, fields
from pathlib import Path
from typing import Dict, List, Tuple

from .unit import Unit


def _row_key(row: Dict[str, str]) -> Tuple[str, ...]:
    """A row is one unit, at one facility, on one date."""
    # Both chains publish a stable per-unit id, so that is the identity.
    # Keying on the footprint instead merged genuinely distinct units: one
    # facility rents two 5x5s at different rates, and the cheaper vanished.
    return (row["date"], row["source"], str(row["facility_id"]), row["unit_id"])


def _facility_key(row: Dict[str, str]) -> Tuple[str, ...]:
    """One facility's inventory on one date -- what a single scrape replaces."""
    return (row["date"], row["source"], str(row["facility_id"]))


def _sort_key(row: Dict[str, str]) -> Tuple[str, ...]:
    """Group the file by date, chain, and facility for readable diffs."""
    return (row["date"], row["source"], row["postal_code"], row["street"],
            row["unit_label"], row["price"])


def append_snapshot(units: List[Unit], out: Path) -> Tuple[int, int]:
    """Merge new rows into the CSV log. Returns (rows before, rows after)."""
    rows: Dict[Tuple[str, ...], Dict[str, str]] = {}
    if out.exists():
        with out.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                rows[_row_key(row)] = row
    before = len(rows)

    fresh = [{k: "" if v is None else str(v) for k, v in asdict(u).items()} for u in units]

    # A second run on the same day replaces a facility's inventory rather than
    # merging into it: a unit rented since the morning is simply gone from the
    # page, and merging would keep advertising it. Only the facilities this run
    # actually reached are cleared, so one whose page failed keeps the rows it
    # last reported, and every earlier day stays untouched either way.
    rescraped = {_facility_key(row) for row in fresh}
    rows = {key: row for key, row in rows.items() if _facility_key(row) not in rescraped}

    for row in fresh:
        rows[_row_key(row)] = row

    ordered = sorted(rows.values(), key=_sort_key)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[f.name for f in fields(Unit)])
        writer.writeheader()
        writer.writerows(ordered)
    return before, len(ordered)
