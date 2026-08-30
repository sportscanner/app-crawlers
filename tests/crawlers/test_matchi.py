from datetime import date

from sportscanner.crawlers.parsers.matchi.core.schema import MatchiSlot
from sportscanner.crawlers.parsers.matchi.core.strategy import (
    _COURT_INFO_PATTERN,
    MatchiSlotFetcher,
)
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.storage.postgres.utils import generate_composite_key

ORGANISATION_WEBSITE = "https://www.matchi.se"


def _make_venue(slug: str) -> SportsVenue:
    return SportsVenue(
        composite_key=generate_composite_key([ORGANISATION_WEBSITE, slug]),
        organisation="Matchi",
        organisation_website=ORGANISATION_WEBSITE,
        venue_name="Test Facility",
        slug=slug,
        postcode="E1 6AN",
        address="London",
        latitude=51.5,
        longitude=-0.1,
        sports=["padel"],
    )


def _make_slot(slug: str) -> MatchiSlot:
    return MatchiSlot(
        facility_id="123",
        facility_name="Test Facility",
        facility_slug=slug,
        start_timestamp_ms=1789430400000,
        end_timestamp_ms=1789434000000,
        slot_ids=["a", "b"],
        duration_minutes=60,
    )


def test_court_info_pattern_extracts_sport_and_status():
    assert _COURT_INFO_PATTERN.search("Padel OUTDOORS").groups() == ("Padel", "OUTDOORS")
    assert _COURT_INFO_PATTERN.search("Tennis INDOORS").groups() == ("Tennis", "INDOORS")


def test_to_unified_looks_up_indoor_by_slug_and_sport():
    # Confirmed live: Down Hall Hotel offers both padel and tennis, both
    # outdoor; BSLTC's padel is indoor. Coarser than Playtomic (venue+sport,
    # not per-court) - the finest grain Matchi's own site exposes.
    fetcher = MatchiSlotFetcher(sport_id=5, category="Padel")
    venue_by_slug = {
        "downhallhotel": _make_venue("downhallhotel"),
        "bsltc": _make_venue("bsltc"),
    }
    facility_indoor_maps = {
        "downhallhotel": {"padel": False, "tennis": False},
        "bsltc": {"padel": True},
    }

    outdoor_record = fetcher._to_unified(
        _make_slot("downhallhotel"), venue_by_slug, date(2026, 9, 1), facility_indoor_maps
    )
    indoor_record = fetcher._to_unified(
        _make_slot("bsltc"), venue_by_slug, date(2026, 9, 1), facility_indoor_maps
    )

    assert outdoor_record.indoor is False
    assert indoor_record.indoor is True


def test_to_unified_unknown_facility_defaults_none():
    fetcher = MatchiSlotFetcher(sport_id=5, category="Padel")
    venue_by_slug = {"unmapped": _make_venue("unmapped")}

    record = fetcher._to_unified(
        _make_slot("unmapped"), venue_by_slug, date(2026, 9, 1), facility_indoor_maps={}
    )

    assert record.indoor is None
