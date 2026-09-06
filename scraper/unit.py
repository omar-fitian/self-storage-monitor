"""Unit dataclass and validation"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


# Bounding box for the Charlotte metro.
# Need to automate this when I introduce market-selection
CHARLOTTE_BBOX = (34.80, 35.60, -81.40, -80.40)  # lat min, lat max, lng min, lng max

# Words either chain uses for a vehicle/RV/boat space rather than a storage unit.
VEHICLE_WORDS = ("parking", "vehicle", "rv", "boat")

# Charlotte's day, not the machine's: a laptop in Chicago and a UTC CI runner
# would disagree, and since the date is part of a row's identity, one run
# would append a second day instead of replacing the first. Not plain UTC
# either: a 9pm scrape in Charlotte is already tomorrow there. Read once at
# import, so every row in a run carries the same date.
CAPTURE_DATE = datetime.now(timezone.utc).astimezone(
    ZoneInfo("America/New_York")).date().isoformat()


class ValidationError(ValueError):
    """Raised when a parsed record cannot be trusted."""


@dataclass(frozen=True, kw_only=True)
class Unit:
    """One available unit's advertised rates on one capture date."""

    date: str = CAPTURE_DATE        # the run's capture date; see above
    source: str
    facility_id: Optional[int]
    unit_id: str                    # the chain's own sku
    street: str
    city: str
    state: str
    postal_code: str
    lat: float
    lng: float
    unit_label: str                 # "5x10", or "40 ft" / "Parking" for vehicle spaces
    width_ft: Optional[float]
    length_ft: Optional[float]
    height_ft: Optional[float]      # A couple of units are half-height
    area_sqft: Optional[float]      # the cross-chain comparison key; None only for parking
    category: str                   # the chain's incomparable label (a medium to one chain may be a large to another chain)
    price: float                    # online-only rate, after any promotion
    regular_price: Optional[float]  # walk-in rate

    @property
    def is_parking(self) -> bool:
        return any(word in self.category.lower() for word in VEHICLE_WORDS)

    def __post_init__(self) -> None:
        """Validate the unit."""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.date):
            raise ValidationError(f"date {self.date!r} is not YYYY-MM-DD")

        for name in ("source", "unit_id", "street", "city", "state", "postal_code", "unit_label"):
            if not str(getattr(self, name)).strip():
                raise ValidationError(f"{name} is empty for facility {self.facility_id!r}")

        lat_min, lat_max, lng_min, lng_max = CHARLOTTE_BBOX
        if not (lat_min <= self.lat <= lat_max and lng_min <= self.lng <= lng_max):
            raise ValidationError(
                f"coordinates ({self.lat}, {self.lng}) for {self.street!r} fall outside "
                f"the Charlotte metro bounding box"
            )

        if self.area_sqft is None:
            # Only a parking space may lack a footprint. A storage unit with no
            # area means the size failed to parse, which must not pass silently.
            if not self.is_parking:
                raise ValidationError(
                    f"storage unit {self.unit_label!r} has no area; only parking "
                    f"spaces may be stored without one"
                )
        elif not 0 < self.area_sqft < 5000:
            raise ValidationError(f"area {self.area_sqft} sq ft for {self.unit_label!r} is implausible")

        if not 0 < self.price < 2000:
            raise ValidationError(f"price {self.price} for {self.unit_label!r} is not a plausible rate")

        if self.regular_price is not None:
            if not 0 < self.regular_price < 5000:
                raise ValidationError(
                    f"regular price {self.regular_price} for {self.unit_label!r} is implausible")
            if self.regular_price < self.price:
                # A promotion cannot raise the price; this means the two rates
                # were read the wrong way round.
                raise ValidationError(
                    f"regular price {self.regular_price} is below the online price "
                    f"{self.price} for {self.unit_label!r}")
