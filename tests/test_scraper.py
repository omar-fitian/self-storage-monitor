"""Tests for scraper.py.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import scraper
from scraper import scraping
from scraper.saving import append_snapshot
from scraper.parsing import (
    parse_cubesmart_facility,
    parse_cubesmart_listing,
    parse_publicstorage_listing,
    parse_publicstorage_store,
    parse_unit_size,
)
from scraper.scraping import scrape_cubesmart
from scraper.unit import Unit, ValidationError

FIXTURES = Path(__file__).parent / "fixtures"
DAY = "2026-08-29"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def cs_listing() -> str:
    return _fixture("cubesmart_listing.html")


@pytest.fixture
def cs_facility() -> str:
    return _fixture("cubesmart_facility.html")


@pytest.fixture
def ps_listing() -> str:
    return _fixture("publicstorage_listing.html")


@pytest.fixture
def ps_store() -> str:
    return _fixture("publicstorage_store.html")


@pytest.fixture
def facility_meta() -> dict:
    return {
        "facility_id": 4144, "street": "1451 Bryant St", "city": "Charlotte",
        "state": "NC", "postal_code": "28208", "lat": 35.22733, "lng": -80.86679,
        "url": "https://www.cubesmart.com/x/4144.html",
    }


class TestCaptureDate:
    """The capture date is Charlotte's day, fixed when the module is imported."""

    def test_the_timezone_database_is_installed(self):
        """ZoneInfo carries no data of its own on Windows: without the tzdata
        package every run would fail at import, and only here would it show."""
        assert ZoneInfo("America/New_York").tzname(datetime(2026, 1, 15)) == "EST"
        assert ZoneInfo("America/New_York").tzname(datetime(2026, 7, 15)) == "EDT"

    def test_is_charlottes_day_and_not_the_runners(self):
        """A CI runner an hour past midnight UTC is still on Charlotte's
        previous day, and the row has to be filed under that."""
        charlotte = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York"))
        assert scraper.DAY == charlotte.date().isoformat()

    def test_is_iso_formatted_so_a_unit_accepts_it(self):
        """The Unit record rejects anything that is not YYYY-MM-DD."""
        assert Unit(
            date=scraper.DAY, source="cubesmart", facility_id=1, unit_id="s1",
            street="1 Test St", city="Charlotte", state="NC", postal_code="28204",
            lat=35.2, lng=-80.8, unit_label="5x10", width_ft=5.0, length_ft=10.0,
            height_ft=8.0, area_sqft=50.0, category="small", price=49.0,
            regular_price=None,
        ).date == scraper.DAY


class TestParseUnitSize:
    @pytest.mark.parametrize("name,expected", [
        ("5x10",        ("5x10", 5.0, 10.0, None, 50.0)),
        ("5'x10'",      ("5x10", 5.0, 10.0, None, 50.0)),
        ("5'x5'x8'",    ("5x5", 5.0, 5.0, 8.0, 25.0)),
        ("10'x7.5'x8'", ("7.5x10", 7.5, 10.0, 8.0, 75.0)),
        ("5'x5'x4'",    ("5x5", 5.0, 5.0, 4.0, 25.0)),   # half-height: height kept
    ])
    def test_reads_footprint_height_and_area(self, name, expected):
        assert parse_unit_size(name) == expected

    def test_footprint_is_order_independent(self):
        """A 10'x5' and a 5'x10' are the same unit and must compare equal."""
        assert parse_unit_size("10'x5'x8'") == parse_unit_size("5'x10'x8'")

    @pytest.mark.parametrize("name,label,length", [("20", "20 ft", 20.0), ("40'", "40 ft", 40.0)])
    def test_a_bare_number_is_a_parking_length(self, name, label, length):
        """CubeSmart advertises RV spaces as "20"/"40" -- feet of length, no width."""
        assert parse_unit_size(name) == (label, None, length, None, None)

    def test_names_without_measurements_are_not_guessed(self):
        assert parse_unit_size("Wine locker") is None
        assert parse_unit_size("Parking") is None
        assert parse_unit_size("") is None


class TestCubeSmartListing:
    def test_extracts_identity_coordinates_and_page_url(self, cs_listing):
        facilities = parse_cubesmart_listing(cs_listing)
        assert [f["facility_id"] for f in facilities] == [4144, 4428]

        first = facilities[0]
        assert first["street"] == "1451 Bryant St"
        assert (first["city"], first["state"], first["postal_code"]) == ("Charlotte", "NC", "28208")
        assert first["lat"] == pytest.approx(35.22733)
        assert first["url"].endswith("/charlotte-self-storage/4144.html")

    def test_a_marker_without_an_address_is_skipped_not_merged(self, cs_listing):
        """Facility 9999 has coordinates but no popup; it must not absorb the next."""
        facilities = parse_cubesmart_listing(cs_listing)
        assert 9999 not in [f["facility_id"] for f in facilities]
        assert facilities[1]["lat"] == pytest.approx(35.20440)  # 4428's own, not 9999's


class TestCubeSmartFacility:
    def test_joins_json_ld_dimensions_to_rendered_card_prices(self, cs_facility, facility_meta):
        units = parse_cubesmart_facility(cs_facility, facility_meta)
        assert {(u.unit_label, u.price) for u in units} == {
            ("5x5", 28.8), ("5x5", 24.0), ("5x10", 60.0), ("7.5x10", 65.4),
            ("10x20", 79.2), ("40 ft", 77.0), ("2x3", 43.0),
        }

    def test_a_length_only_parking_space_is_kept(self, cs_facility, facility_meta):
        """CubeSmart's RV spaces are named "40" -- feet, no width, so no area."""
        unit = next(u for u in parse_cubesmart_facility(cs_facility, facility_meta)
                    if u.unit_label == "40 ft")
        assert (unit.length_ft, unit.width_ft, unit.area_sqft) == (40.0, None, None)
        assert unit.category == "parking"

    def test_every_unit_carries_its_sku_as_identity(self, cs_facility, facility_meta):
        units = parse_cubesmart_facility(cs_facility, facility_meta)
        assert all(u.unit_id for u in units)
        assert len({u.unit_id for u in units}) == len(units)

    def test_a_card_with_no_matching_sku_is_dropped(self, cs_facility, facility_meta):
        """The stray card must not borrow another unit's dimensions."""
        units = parse_cubesmart_facility(cs_facility, facility_meta)
        assert 999.0 not in [u.price for u in units]

    def test_reversed_footprints_normalise(self, cs_facility, facility_meta):
        """The page lists 10'x5'; it must be stored as 5x10 to match rivals."""
        unit = next(u for u in parse_cubesmart_facility(cs_facility, facility_meta)
                    if u.price == 60.0)
        assert unit.unit_label == "5x10"
        assert (unit.width_ft, unit.length_ft) == (5.0, 10.0)

    def test_height_is_preserved(self, cs_facility, facility_meta):
        """Two 5x5s at different heights are different products."""
        heights = {u.price: u.height_ft for u in parse_cubesmart_facility(cs_facility, facility_meta)}
        assert heights[28.8] == 8.0
        assert heights[24.0] == 4.0

    def test_records_the_chains_own_label_without_relying_on_it(self, cs_facility, facility_meta):
        """CubeSmart calls a 75 sq ft unit "small" -- recorded, but not a comparison key."""
        unit = next(u for u in parse_cubesmart_facility(cs_facility, facility_meta)
                    if u.unit_label == "7.5x10")
        assert unit.category == "small"
        assert unit.area_sqft == 75.0

    def test_both_price_tiers_are_kept(self, cs_facility, facility_meta):
        """data-unitprice rounds $28.80 to 29, so the printed figures are read."""
        unit = next(u for u in parse_cubesmart_facility(cs_facility, facility_meta)
                    if u.unit_label == "5x5" and u.height_ft == 8.0)
        assert unit.price == 28.80          # promotional online rate
        assert unit.regular_price == 48.00  # walk-in rate it discounts

    def test_a_unit_with_no_printed_price_falls_back_to_the_attribute(
        self, cs_facility, facility_meta
    ):
        """Wine lockers print no price block; dropping them lost real units."""
        unit = next(u for u in parse_cubesmart_facility(cs_facility, facility_meta)
                    if u.unit_label == "2x3")
        assert unit.price == 43.0
        assert unit.regular_price is None   # no walk-in rate is printed either

    def test_inherits_the_facility_address(self, cs_facility, facility_meta):
        units = parse_cubesmart_facility(cs_facility, facility_meta)
        assert {u.street for u in units} == {"1451 Bryant St"}


class TestPublicStorageListing:
    def test_collects_each_store_url_once(self, ps_listing):
        assert parse_publicstorage_listing(ps_listing) == [
            "https://www.publicstorage.com/self-storage-nc-charlotte/2334.html",
            "https://www.publicstorage.com/self-storage-nc-charlotte/1796.html",
        ]

    def test_ignores_pages_without_stores(self):
        assert parse_publicstorage_listing("<html><body>Nothing here</body></html>") == []


class TestPublicStorageStore:
    def test_identity_comes_from_the_structured_data(self, ps_store):
        unit = parse_publicstorage_store(ps_store)[0]
        assert unit.facility_id == 1164
        assert unit.street == "5748 N Tryon Street"
        assert (unit.city, unit.state, unit.postal_code) == ("Charlotte", "NC", "28213")
        assert unit.lat == pytest.approx(35.28749)

    def test_prices_come_from_the_card_not_the_structured_data(self, ps_store):
        """The JSON-LD band is the in-store rate +/-20%; $22 is what you pay."""
        unit = next(u for u in parse_publicstorage_store(ps_store)
                    if u.unit_id == "V_1577824")
        assert unit.price == 22.0        # card's Online-Only Price
        assert unit.price != 29.0        # JSON-LD low end -- quoted to nobody

    def test_sizes_come_from_the_card_not_the_structured_data(self, ps_store):
        """The JSON-LD calls this 10x30; the store rents a 30x30."""
        unit = next(u for u in parse_publicstorage_store(ps_store)
                    if u.unit_id == "V_583663")
        assert unit.unit_label == "30x30"
        assert unit.area_sqft == 900.0

    def test_a_unit_the_structured_data_calls_sizeless_parking_gets_its_footprint(self, ps_store):
        """JSON-LD names V_1518027 "Parking" with no dimensions; the card has 10x20."""
        unit = next(u for u in parse_publicstorage_store(ps_store)
                    if u.unit_id == "V_1518027")
        assert unit.unit_label == "10x20"
        assert unit.area_sqft == 200.0
        assert unit.category == "parking"

    def test_both_price_tiers_are_kept(self, ps_store):
        unit = next(u for u in parse_publicstorage_store(ps_store)
                    if u.unit_id == "V_1577824")
        assert (unit.price, unit.regular_price) == (22.0, 36.0)

    def test_category_uses_the_chains_own_size_word(self, ps_store):
        units = {u.unit_id: u for u in parse_publicstorage_store(ps_store)}
        assert units["V_1577824"].category == "small"
        # A vehicle space that is also a storage unit keeps its size word.
        assert units["V_583663"].category == "large"

    def test_every_card_becomes_one_row(self, ps_store):
        units = parse_publicstorage_store(ps_store)
        assert {(u.unit_label, u.price) for u in units} == {
            ("5x5", 22.0), ("10x20", 70.0), ("30x30", 419.0),
        }

    def test_a_list_item_with_no_unit_id_is_ignored(self, ps_store):
        """The promo tile is an <li> in the same list and is not a unit."""
        assert len(parse_publicstorage_store(ps_store)) == 3

    def test_returns_nothing_for_a_page_with_no_store(self):
        assert parse_publicstorage_store("<html><body>404</body></html>") == []


class TestCrossChainComparability:
    def test_the_same_footprint_gets_the_same_label_from_both_chains(
        self, cs_facility, ps_store, facility_meta
    ):
        """The point of the whole schema: 5x5 means 5x5 on either chain.

        The two are read from completely different markup -- CubeSmart from
        JSON-LD dimensions joined to a card, Public Storage from a card's
        data-unitsize -- and still have to land on one comparable value.
        """
        cube = [u for u in parse_cubesmart_facility(cs_facility, facility_meta)
                if u.unit_label == "5x5"]
        public = [u for u in parse_publicstorage_store(ps_store)
                  if u.unit_label == "5x5"]
        assert cube and public

        assert {u.area_sqft for u in cube} == {u.area_sqft for u in public} == {25.0}
        # Comparable, and genuinely different: that difference is the product.
        assert min(u.price for u in cube) != min(u.price for u in public)


class TestParkingValidation:
    def test_a_storage_unit_without_an_area_is_rejected(self):
        """Only parking may lack a footprint; a sizeless storage unit is a parse bug."""
        with pytest.raises(ValidationError, match="only parking"):
            Unit(date=DAY, source="cubesmart", facility_id=1, unit_id="s1",
                 street="1 Test St", city="Charlotte", state="NC", postal_code="28204",
                 lat=35.2, lng=-80.8, unit_label="?", width_ft=None, length_ft=None,
                 height_ft=None, area_sqft=None, category="small", price=49.0,
                 regular_price=None)

    def test_a_parking_space_without_an_area_is_accepted(self):
        unit = Unit(date=DAY, source="cubesmart", facility_id=1, unit_id="s1",
                    street="1 Test St", city="Charlotte", state="NC", postal_code="28204",
                    lat=35.2, lng=-80.8, unit_label="40 ft", width_ft=None, length_ft=40.0,
                    height_ft=None, area_sqft=None, category="parking", price=77.0,
                    regular_price=None)
        assert unit.is_parking and unit.area_sqft is None


class TestUnitValidation:
    def _unit(self, **overrides) -> Unit:
        defaults = dict(
            date=DAY, source="cubesmart", facility_id=1, unit_id="sku-1",
            street="1 Test St", city="Charlotte", state="NC", postal_code="28204",
            lat=35.2, lng=-80.8, unit_label="5x10", width_ft=5.0, length_ft=10.0,
            height_ft=8.0, area_sqft=50.0, category="small", price=49.0,
            regular_price=80.0,
        )
        return Unit(**{**defaults, **overrides})

    def test_accepts_a_plausible_record(self):
        assert self._unit().unit_label == "5x10"

    def test_rejects_coordinates_outside_the_market(self):
        with pytest.raises(ValidationError, match="bounding box"):
            self._unit(lat=40.71, lng=-74.00)

    def test_rejects_a_blank_required_field(self):
        with pytest.raises(ValidationError, match="street is empty"):
            self._unit(street="  ")

    def test_rejects_a_unit_with_no_identity(self):
        with pytest.raises(ValidationError, match="unit_id is empty"):
            self._unit(unit_id="")

    def test_rejects_an_implausible_rate(self):
        with pytest.raises(ValidationError, match="not a plausible rate"):
            self._unit(price=9500.0)

    def test_rejects_a_regular_price_below_the_online_price(self):
        """A promotion cannot raise the price; this means the tiers were swapped."""
        with pytest.raises(ValidationError, match="below the online price"):
            self._unit(price=80.0, regular_price=49.0)

    def test_rejects_an_implausible_area(self):
        with pytest.raises(ValidationError, match="implausible"):
            self._unit(area_sqft=99999.0)

    def test_rejects_a_malformed_date(self):
        with pytest.raises(ValidationError, match="not YYYY-MM-DD"):
            self._unit(date="29/08/2026")


class TestAppendSnapshot:
    def _units(self, day, cs_facility, facility_meta):
        """The parsed rows, restamped -- the capture date is fixed at import."""
        return [replace(u, date=day)
                for u in parse_cubesmart_facility(cs_facility, facility_meta)]

    def test_writes_every_unit_as_its_own_row(self, tmp_path, cs_facility, facility_meta):
        out = tmp_path / "units.csv"
        _, after = append_snapshot(self._units(DAY, cs_facility, facility_meta), out)
        assert after == 7

        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert {r["unit_label"] for r in rows} == {"5x5", "5x10", "7.5x10", "10x20", "40 ft", "2x3"}

    def test_two_units_of_one_size_at_different_prices_both_survive(self, tmp_path, cs_facility, facility_meta):
        """Keyed on the unit's own id: the fixture's two 5x5s ($28.80, $24) are distinct."""
        out = tmp_path / "units.csv"
        append_snapshot(self._units(DAY, cs_facility, facility_meta), out)
        rows = [r for r in csv.DictReader(out.open(encoding="utf-8")) if r["unit_label"] == "5x5"]
        assert sorted(float(r["price"]) for r in rows) == [24.0, 28.8]

    def test_parking_rows_are_written_with_an_empty_area(self, tmp_path, cs_facility, facility_meta):
        out = tmp_path / "units.csv"
        append_snapshot(self._units(DAY, cs_facility, facility_meta), out)
        row = next(r for r in csv.DictReader(out.open(encoding="utf-8")) if r["unit_label"] == "40 ft")
        assert row["area_sqft"] == "" and row["width_ft"] == "" and row["length_ft"] == "40.0"

    def test_a_missing_height_is_written_as_empty_not_zero(self, tmp_path, ps_store):
        out = tmp_path / "units.csv"
        append_snapshot(parse_publicstorage_store(ps_store), out)
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert all(r["height_ft"] == "" for r in rows)

    def test_rerunning_the_same_day_replaces_rather_than_duplicates(
        self, tmp_path, cs_facility, facility_meta
    ):
        out = tmp_path / "units.csv"
        append_snapshot(self._units(DAY, cs_facility, facility_meta), out)
        before, after = append_snapshot(self._units(DAY, cs_facility, facility_meta), out)
        assert (before, after) == (7, 7)

    def test_a_unit_rented_between_two_runs_stops_being_advertised(
        self, tmp_path, cs_facility, facility_meta
    ):
        """The second run is the facility's whole inventory, not an addition to it."""
        out = tmp_path / "units.csv"
        units = self._units(DAY, cs_facility, facility_meta)
        append_snapshot(units, out)

        # Same facility, same day, two of its units now gone from the page.
        before, after = append_snapshot(units[:-2], out)
        assert (before, after) == (7, 5)

        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert {r["unit_id"] for r in rows} == {u.unit_id for u in units[:-2]}

    def test_a_facility_that_failed_today_keeps_the_rows_it_last_reported(
        self, tmp_path, cs_facility, facility_meta
    ):
        """Only facilities this run actually reached are cleared."""
        out = tmp_path / "units.csv"
        other = Unit(date=DAY, source="cubesmart", facility_id=9999, unit_id="other-1",
                     street="9 Other St", city="Charlotte", state="NC", postal_code="28204",
                     lat=35.2, lng=-80.8, unit_label="5x10", width_ft=5.0, length_ft=10.0,
                     height_ft=8.0, area_sqft=50.0, category="small", price=49.0,
                     regular_price=80.0)
        append_snapshot(self._units(DAY, cs_facility, facility_meta) + [other], out)

        # A run in which facility 9999's page failed and returned nothing.
        before, after = append_snapshot(self._units(DAY, cs_facility, facility_meta), out)
        assert (before, after) == (8, 8)

    def test_a_new_day_accumulates_history(self, tmp_path, cs_facility, facility_meta):
        out = tmp_path / "units.csv"
        append_snapshot(self._units("2026-08-28", cs_facility, facility_meta), out)
        before, after = append_snapshot(self._units("2026-08-29", cs_facility, facility_meta), out)
        assert (before, after) == (7, 14)

        dates = {r["date"] for r in csv.DictReader(out.open(encoding="utf-8"))}
        assert dates == {"2026-08-28", "2026-08-29"}



class TestChainFailure:
    """A chain that reached its facilities and parsed none of them has failed."""

    def test_a_chain_whose_every_facility_page_failed_raises(
        self, monkeypatch, cs_listing
    ):
        market, _ = scraper.CHAINS["cubesmart"]

        def fetch(url, timeout=30):
            if url == market:
                return cs_listing
            raise OSError("connection reset")

        monkeypatch.setattr(scraping, "fetch", fetch)
        monkeypatch.setattr(scraping, "REQUEST_DELAY_SECONDS", 0)
        # Returning [] here would let main() commit a day holding one chain.
        with pytest.raises(ValueError, match="no units parsed"):
            scrape_cubesmart(market)


class TestMain:
    """The one function no test used to reach, which is where the last bug lived."""

    @pytest.fixture(autouse=True)
    def _detach_the_reject_log(self):
        """main() attaches a file handler and, being a process entry point, never
        detaches it. Left in place it would keep writing into a deleted tmp_path."""
        handlers = list(scraper.logger.handlers)
        yield
        scraper.logger.handlers = handlers

    def test_a_successful_run_writes_the_csv_and_the_reject_log(self, tmp_path, monkeypatch):
        unit = Unit(date=DAY, source="cubesmart", facility_id=1, unit_id="sku-1",
                    street="1 Test St", city="Charlotte", state="NC", postal_code="28204",
                    lat=35.2, lng=-80.8, unit_label="5x10", width_ft=5.0, length_ft=10.0,
                    height_ft=8.0, area_sqft=50.0, category="small", price=49.0,
                    regular_price=80.0)
        out, rejects = tmp_path / "units.csv", tmp_path / "rejects.log"
        monkeypatch.setattr(scraper, "DEFAULT_OUT", out)
        monkeypatch.setattr(scraper, "REJECTS_OUT", rejects)
        monkeypatch.setattr(scraper, "CHAINS",
                            {"cubesmart": ("http://test", lambda start_url: [unit])})

        assert scraper.main() == 0
        assert [r["unit_id"] for r in csv.DictReader(out.open(encoding="utf-8"))] == ["sku-1"]
        assert rejects.exists()

    def test_a_drop_from_the_parsing_module_reaches_the_reject_log(self, tmp_path, monkeypatch):
        """The reject log is opened here but the drops happen in parsing.py, so
        every module has to log under the same name for this to arrive."""
        html = _fixture("cubesmart_facility.html")
        meta = {"facility_id": 4144, "street": "1451 Bryant St", "city": "Charlotte",
                "state": "NC", "postal_code": "28208", "lat": 35.22733, "lng": -80.86679,
                "url": "https://www.cubesmart.com/x/4144.html"}
        rejects = tmp_path / "rejects.log"
        monkeypatch.setattr(scraper, "DEFAULT_OUT", tmp_path / "units.csv")
        monkeypatch.setattr(scraper, "REJECTS_OUT", rejects)
        monkeypatch.setattr(scraper, "CHAINS", {
            "cubesmart": ("http://test",
                          lambda start_url: parse_cubesmart_facility(html, meta)),
        })

        assert scraper.main() == 0
        # The card the fixture gives no size for.
        assert "bbbbbbbb-9999-9999-9999-999999999999" in rejects.read_text(encoding="utf-8")

    def test_one_chain_failing_still_saves_the_other(self, tmp_path, monkeypatch):
        unit = Unit(date=DAY, source="cubesmart", facility_id=1, unit_id="sku-1",
                    street="1 Test St", city="Charlotte", state="NC", postal_code="28204",
                    lat=35.2, lng=-80.8, unit_label="5x10", width_ft=5.0, length_ft=10.0,
                    height_ft=8.0, area_sqft=50.0, category="small", price=49.0,
                    regular_price=80.0)
        out, rejects = tmp_path / "units.csv", tmp_path / "rejects.log"
        monkeypatch.setattr(scraper, "DEFAULT_OUT", out)
        monkeypatch.setattr(scraper, "REJECTS_OUT", rejects)

        def broken(start_url):
            raise ValueError("layout change")

        monkeypatch.setattr(scraper, "CHAINS", {
            "cubesmart": ("http://test", lambda start_url: [unit]),
            "publicstorage": ("http://test", broken),
        })

        # Non-zero so the run is visibly degraded, but the good chain is kept.
        assert scraper.main() == 1
        assert out.exists()
        assert "layout change" in rejects.read_text(encoding="utf-8")


class TestDroppedUnits:
    """A unit that cannot be stored has to say enough to be chased down later."""

    def test_a_drop_names_both_the_unit_and_the_page(self, caplog, cs_facility, facility_meta):
        # The fixture holds one card whose SKU has no size in the page data.
        with caplog.at_level(logging.WARNING, logger="scraper"):
            parse_cubesmart_facility(cs_facility, facility_meta)

        messages = [r.getMessage() for r in caplog.records]
        assert len(messages) == 1
        # Enough to reopen the page and find the unit that went missing.
        assert "bbbbbbbb-9999-9999-9999-999999999999" in messages[0]
        assert facility_meta["url"] in messages[0]
