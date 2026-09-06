"""Turning a fetched page into Unit records.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Iterator, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .unit import VEHICLE_WORDS, Unit, ValidationError

# Every module logs to this one name so that the reject-log handler main()
# attaches catches drops from all of them, not just from this file.
logger = logging.getLogger("scraper")


def _jsonld_items(soup: BeautifulSoup) -> Iterator[dict]:
    """Yield every schema.org item embedded in a page, flattening @graph."""
    for block in soup.select('script[type="application/ld+json"]'):
        # A page carries several of these blocks -- a Public Storage market
        # page has three -- and each is decoded alone so that one block the
        # chain renders badly costs only itself, not the rest of the page.
        try:
            data = json.loads(block.string or "")
        except json.JSONDecodeError:
            continue

        # schema.org allows three shapes at the top of a block, and these two
        # chains between them use all three: a bare object, a list of objects,
        # or one wrapper object holding the real items under @graph. Callers
        # want the items, so the list and the wrapper are both flattened away
        # and every caller can just filter on @type.
        for item in data if isinstance(data, list) else [data]:
            # A list may hold anything, and callers are handed these to filter
            # on @type, so a bare string or number is dropped here rather than
            # blowing up in the caller's .get().
            if not isinstance(item, dict):
                continue
            # Flattening @graph is what puts CubeSmart's ItemList of units in
            # reach; without it the block yields only the wrapper.
            if "@graph" in item:
                yield from item["@graph"]
            else:
                yield item


def _prose(soup: BeautifulSoup) -> None:
    """Drop script and style so the remaining text is what a visitor reads."""
    # Only once the structured data has been taken: this deletes the JSON-LD
    # along with everything else.
    for tag in soup(["script", "style"]):
        tag.decompose()


# Both chains put the facility's own number in its page's filename.
_FACILITY_ID_IN_URL = re.compile(r"/(\d+)\.html")


# --- CubeSmart -------------------------------------------------------------
#
# The market page builds its results map client-side, pushing one object per
# facility onto a markerData array; each push carries the facility's
# coordinates and a link to its own page. That page lists every unit twice:
# as JSON-LD Products (which carry exact dimensions but no price) and as
# rendered cards (which carry the price and CubeSmart's own size label).
# Joining the two on the unit's SKU gives dimensions and price together.

# The marker array is JavaScript, not markup, so it is read with expressions
# rather than with the parser. The popup string it carries is HTML, and that
# part is handed back to the parser below.
_CUBE_BLOCK = re.compile(r"markerData\.push\(\{(.*?)\}\);", re.S)
_CUBE_POSITION = re.compile(r"position:\s*\{\s*lat:\s*(-?[\d.]+),\s*lng:\s*(-?[\d.]+)\s*\}")
_CUBE_CONTENT = re.compile(r"content:\s*'(.+?)',\s*disableAutoPan", re.S)

_CUBE_CITY_STATE_ZIP = re.compile(r"^(?P<city>.+?),\s*(?P<state>[A-Z]{2})\s+(?P<zip>\d{5})$")

# data-unitprice is rounded to whole dollars ("29" for a $28.80 unit), so the
# printed prices are preferred -- both tiers, exactly as quoted. Wine lockers
# carry the attribute but print no price block at all, so the attribute is
# kept as a fallback: a rounded rate is better than losing the unit.
_CUBE_ONLINE_PRICE = re.compile(r"\$\s*([\d,.]+)[^$]{0,40}?online price")
_CUBE_STORE_PRICE = re.compile(r"\$\s*([\d,.]+)\s*in store price")


def parse_cubesmart_listing(html: str) -> List[dict]:
    """Extract each facility's identity, coordinates, and page URL."""
    facilities = []
    for block in _CUBE_BLOCK.findall(html):
        position = _CUBE_POSITION.search(block)
        content = _CUBE_CONTENT.search(block)
        if not position or not content:
            continue

        # The address and the facility's own URL are both inside the marker's
        # popup, which arrives as an escaped HTML string.
        popup = BeautifulSoup(content.group(1).replace('\\"', '"'), "lxml")
        heading, link = popup.h3, popup.select_one("a[href]")
        if not heading or not link:
            continue

        # The heading holds the street on one line and "City, ST 12345" on the
        # next, the two split by a <br/>.
        lines = list(heading.stripped_strings)
        parts = _CUBE_CITY_STATE_ZIP.match(lines[-1]) if len(lines) > 1 else None
        page = _FACILITY_ID_IN_URL.search(link["href"])
        if not parts or not page:
            logger.warning("Cannot read a CubeSmart facility from %r", " ".join(lines))
            continue

        facilities.append({
            "facility_id": int(page.group(1)),
            "street": lines[0],
            "city": parts.group("city"),
            "state": parts.group("state"),
            "postal_code": parts.group("zip"),
            "lat": float(position.group(1)),
            "lng": float(position.group(2)),
            "url": urljoin("https://www.cubesmart.com", link["href"]),
        })
    logger.info("Found %d CubeSmart facilities", len(facilities))
    return facilities


def parse_cubesmart_facility(html: str, facility: dict) -> List[Unit]:
    """Parse one CubeSmart facility page into its priced units."""
    soup = BeautifulSoup(html, "lxml")

    # The JSON-LD lists every unit with exact dimensions but no price; the
    # rendered cards carry the price but no dimensions. SKU joins the halves.
    dimensions_by_sku = {
        item.get("sku"): item.get("name")
        for node in _jsonld_items(soup)
        if node.get("@type") == "ItemList"
        for element in node.get("itemListElement", [])
        for item in [element.get("item") or {}]
        if item.get("sku")
    }
    _prose(soup)

    units = []
    # A card's own id is the SKU that joins it to the dimensions above.
    for card in soup.select("li.csStorageSizeDimension[id]"):
        sku = card["id"]
        name = dimensions_by_sku.get(sku)
        if not name:
            logger.warning("Dropped cubesmart unit %s at %s: no matching size in the page data",
                           sku, facility["url"])
            continue

        text = card.get_text(" ", strip=True)
        printed = _CUBE_ONLINE_PRICE.search(text)
        attribute = card.select_one("[data-unitprice]")
        if printed:
            online = _money(printed.group(1))
            regular_match = _CUBE_STORE_PRICE.search(text)
            regular = _money(regular_match.group(1)) if regular_match else None
        elif attribute:
            # Wine lockers print no price block; the attribute is all there is,
            # and it carries no walk-in rate to pair with.
            online, regular = _money(attribute["data-unitprice"]), None
        else:
            logger.warning("Dropped cubesmart unit %s at %s: no price anywhere on the card",
                           sku, facility["url"])
            continue

        group = card.select_one("[data-tab-group]")
        category = group["data-tab-group"].lower() if group else ""
        size = parse_unit_size(name)
        if size is None:
            if any(word in category for word in VEHICLE_WORDS):
                size = UNSIZED_PARKING
            else:
                logger.warning("Dropped cubesmart unit %s at %s: unreadable size %r",
                               sku, facility["url"], name)
                continue
        label, width, length, height, area = size

        try:
            units.append(Unit(
                source="cubesmart",
                facility_id=facility["facility_id"], unit_id=sku,
                street=facility["street"], city=facility["city"],
                state=facility["state"], postal_code=facility["postal_code"],
                lat=facility["lat"], lng=facility["lng"],
                unit_label=label, width_ft=width, length_ft=length,
                height_ft=height, area_sqft=area, category=category,
                price=online, regular_price=regular,
            ))
        except ValidationError as exc:
            logger.warning("Dropped cubesmart unit %s at %s: %s", sku, facility["url"], exc)
    return units


# --- Public Storage --------------------------------------------------------

# The market page names each store. A store page carries its address in
# schema.org JSON-LD and its units as rendered cards.
#
# Only the address is taken from the JSON-LD, because its prices and sizes
# disagree with what the store sells: the price is a band of the in-store rate
# plus or minus 20% (the midpoint IS the in-store rate), so its low end is
# quoted to nobody, and its names call a 30x30 "10x30" and a vehicle space a
# sizeless "Parking". Against the cards, 79 units were priced about 25% high
# and 19 carried the wrong footprint.

_PS_ONLINE_PRICE = re.compile(r"Online-Only Price\s*\$\s*([\d,.]+)")
_PS_STORE_PRICE = re.compile(r"In Store\s*\$\s*([\d,.]+)")
# The chain's own size words, taken from the classes it puts on each card.
_PS_SIZE_CLASS = {"IsSmall": "small", "IsMedium": "medium", "IsLarge": "large"}


def parse_publicstorage_listing(html: str) -> List[str]:
    """Extract the store-page URLs named on a Public Storage market page."""
    urls: List[str] = []
    for item in _jsonld_items(BeautifulSoup(html, "lxml")):
        if item.get("@type") != "SelfStorage":
            continue
        page = str(item.get("@id", "")).split("#")[0]
        if _FACILITY_ID_IN_URL.search(page) and page not in urls:
            urls.append(page)
    logger.info("Found %d Public Storage stores", len(urls))
    return urls


def _publicstorage_facility(soup: BeautifulSoup) -> Optional[dict]:
    """Read the store's address and coordinates from its schema.org block."""
    for item in _jsonld_items(soup):
        if item.get("@type") != "SelfStorage" or not item.get("geo"):
            continue
        address, geo = item.get("address") or {}, item["geo"]
        store_id = _FACILITY_ID_IN_URL.search(str(item.get("@id", "")))
        return {
            "facility_id": int(store_id.group(1)) if store_id else None,
            "street": str(address.get("streetAddress", "")).strip(),
            "city": str(address.get("addressLocality", "")).strip(),
            "state": str(address.get("addressRegion", "")).strip(),
            "postal_code": str(address.get("postalCode", "")).strip(),
            "lat": float(geo["latitude"]),
            "lng": float(geo["longitude"]),
        }
    return None


def parse_publicstorage_store(html: str) -> List[Unit]:
    """Parse one Public Storage store page into its priced units."""
    soup = BeautifulSoup(html, "lxml")
    facility = _publicstorage_facility(soup)
    if facility is None:
        # A whole store, lost without a single unit-level warning to show it.
        logger.warning("Dropped a Public Storage store: no address in its page data")
        return []
    store = facility["facility_id"]
    _prose(soup)

    units = []
    # The unit-card class is also worn by a promotional tile, which carries no
    # unit id; requiring the attribute leaves it out.
    for card in soup.select("li.mobile-unit-list-item[data-unitid]"):
        unit_id = card["data-unitid"]
        size = card.get("data-unitsize", "").removeprefix("Has")
        text = card.get_text(" ", strip=True)
        price = _PS_ONLINE_PRICE.search(text)
        if not size or not price:
            logger.warning(
                "Dropped publicstorage unit %s at store %s: no size or price on the card",
                unit_id, store)
            continue

        regular = _PS_STORE_PRICE.search(text)
        classes = set(card.get("class", []))
        # A vehicle space that is not also a storage unit is parking; one that
        # is both is a storage unit big enough to take a car, so it keeps the
        # chain's own size word.
        if "IsVehicleUnit" in classes and "IsStorageUnit" not in classes:
            category = "parking"
        else:
            category = next((w for c, w in _PS_SIZE_CLASS.items() if c in classes), "")

        parsed = parse_unit_size(size)
        if parsed is None:
            logger.warning("Dropped publicstorage unit %s at store %s: unreadable size %r",
                           unit_id, store, size)
            continue
        label, width, length, height, area = parsed

        try:
            units.append(Unit(
                source="publicstorage", unit_id=unit_id,
                unit_label=label, width_ft=width, length_ft=length,
                height_ft=height, area_sqft=area, category=category,
                price=_money(price.group(1)),
                regular_price=_money(regular.group(1)) if regular else None,
                **facility,
            ))
        except ValidationError as exc:
            logger.warning("Dropped publicstorage unit %s at store %s: %s", unit_id, store, exc)
    return units


# ---------------------------------------------------------------------------
# Sizes and prices
# ---------------------------------------------------------------------------

# Matches the footprint at the start of a unit name e.g. "5x10", "5'x10'", "10'x7.5'x8'"
_DIMENSIONS = re.compile(
    r"""^\s*
    (?P<a>\d+(?:\.\d+)?)\s*'?\s*[xX]\s*
    (?P<b>\d+(?:\.\d+)?)\s*'?
    (?:\s*[xX]\s*(?P<h>\d+(?:\.\d+)?)\s*'?)?
    """,
    re.VERBOSE,
)


# A unit advertised as a bare number is a parking space measured by length
# alone e.g. CubeSmart sells RV spaces as "20", "30", "40" (feet).
_PARKING_LENGTH = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*'?\s*$")

# What a size string resolves to: (label, width, length, height, area). Any of
# width/length/height/area may be None for a parking space.
UnitSize = Tuple[str, Optional[float], Optional[float], Optional[float], Optional[float]]


def _trim(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def parse_unit_size(name: str) -> Optional[UnitSize]:
    """
    Canonicalizes a unit name into a comparable size and calculates area.

    Args:
        name (str): The unit name to standardize (e.g. "5x10", "10x5", "5'x10'", "10'x7.5'x8'", "10'x7.5'x4'").
    Returns:
        UnitSize: A 5-tuple containing the canonicalized name, disaggregated width and length, optional height, and calculated area.
    """
    match = _DIMENSIONS.match(name or "")
    if match:
        side_a, side_b = float(match.group("a")), float(match.group("b"))
        height = float(match.group("h")) if match.group("h") else None
        # Sorted, so however a chain writes it the label comes out the same.
        width, length = sorted((side_a, side_b))
        return f"{_trim(width)}x{_trim(length)}", width, length, height, round(width * length, 1)

    match = _PARKING_LENGTH.match(name or "")
    if match:
        # An RV space sold by length alone: no width, so no area to compute.
        length = float(match.group(1))
        return f"{_trim(length)} ft", None, length, None, None

    # No measurement at all. Callers keep this only where the chain has
    # already said the unit is parking; anywhere else it is a parse failure.
    return None


# A parking space the chain named without any measurement ("Parking").
UNSIZED_PARKING: UnitSize = ("Parking", None, None, None, None)


def _money(text: str) -> Optional[float]:
    """Read the first amount out of a price string, ignoring separators."""
    match = re.search(r"(\d+(?:\.\d+)?)", str(text).replace(",", ""))
    if not match:
        return None
    return float(match.group(1)) or None
