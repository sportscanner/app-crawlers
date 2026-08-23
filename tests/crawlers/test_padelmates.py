from datetime import date, datetime, time
import json
from pathlib import Path

from sportscanner.crawlers.parsers.core.schemas import (
    AdditionalRequestMetadata,
    RawResponseData,
    RequestDetailsWithMetadata,
    UnifiedParserSchema,
)
from sportscanner.crawlers.parsers.padelmates.core.schema import PadelMatesSlot
from sportscanner.crawlers.parsers.padelmates.core.strategy import (
    CLUB_SLUG_TO_CLUB_ID,
    PADEL_MATES_ORGANISATION_WEBSITE,
    PadelMatesRequestStrategy,
    PadelMatesResponseParserStrategy,
)
from sportscanner.crawlers.parsers.padelmates.padel.scraper import (
    PadelMatesPadelCrawler,
    coroutines,
)
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.storage.postgres.utils import generate_composite_key

ORGANISATION = "Padel Mates"
ORGANISATION_WEBSITE = PADEL_MATES_ORGANISATION_WEBSITE


def _make_sports_venue(slug: str, name: str) -> SportsVenue:
    return SportsVenue(
        composite_key=generate_composite_key([ORGANISATION_WEBSITE, slug]),
        organisation=ORGANISATION,
        organisation_website=ORGANISATION_WEBSITE,
        venue_name=name,
        slug=slug,
        postcode="IG1 3PS",
        address="Wellness Suite, Rocket Padel, 2 The Drive, Ilford, IG1 3PS",
        latitude=51.572448,
        longitude=0.058199,
        sports=["padel"],
    )


def test_padelmates_slot_schema():
    slot_dict = {
        "courtName": "Court 1",
        "courtId": "court_123",
        "slotId": "slot_456",
        "duration": 60,
        "price": 40.0,
        "startDatetime": "2026-08-24T08:00:00+00:00",
        "endDatetime": "2026-08-24T09:00:00+00:00",
        "startTime": "08:00",
        "endTime": "09:00",
        "reservedIntersection": False,
    }
    slot = PadelMatesSlot(**slot_dict)
    assert slot.courtName == "Court 1"
    assert slot.duration == 60
    assert slot.price == 40.0
    assert slot.reservedIntersection is False


def test_padelmates_request_strategy():
    strategy = PadelMatesRequestStrategy()
    venue = _make_sports_venue("rocketpadelilford", "Rocket Padel Ilford")
    fetch_date = date(2026, 8, 24)
    reqs = strategy.generate_request_details(venue, fetch_date)

    assert len(reqs) == 1
    req = reqs[0]
    assert "fastapi-production-fargate.padelmates.io" in req.url
    assert f"club_id={CLUB_SLUG_TO_CLUB_ID['rocketpadelilford']}" in req.url
    assert req.metadata.category == "Padel"
    assert req.metadata.date == fetch_date
    assert req.metadata.booking_url == f"{ORGANISATION_WEBSITE}/club/rocketpadelilford"


def test_padelmates_unknown_slug_request_strategy():
    strategy = PadelMatesRequestStrategy()
    venue = _make_sports_venue("non_existent_slug", "Unknown Club")
    reqs = strategy.generate_request_details(venue, date(2026, 8, 24))
    assert reqs == []


def test_padelmates_response_parser_strategy():
    venue = _make_sports_venue("rocketpadelilford", "Rocket Padel Ilford")
    parser = PadelMatesResponseParserStrategy()

    raw_content = {
        "allSlots": [
            {
                "courtName": "Court 1",
                "courtId": "c1",
                "slotId": "s1",
                "duration": 60,
                "price": 40.0,
                "startDatetime": "2026-08-24T08:00:00+00:00",
                "endDatetime": "2026-08-24T09:00:00+00:00",
                "startTime": "08:00",
                "endTime": "09:00",
                "reservedIntersection": False,
            },
            {
                "courtName": "Court 2",
                "courtId": "c2",
                "slotId": "s2",
                "duration": 60,
                "price": 40.0,
                "startDatetime": "2026-08-24T08:00:00+00:00",
                "endDatetime": "2026-08-24T09:00:00+00:00",
                "startTime": "08:00",
                "endTime": "09:00",
                "reservedIntersection": False,
            },
            {
                "courtName": "Court 3",
                "courtId": "c3",
                "slotId": "s3",
                "duration": 60,
                "price": 40.0,
                "startDatetime": "2026-08-24T08:00:00+00:00",
                "endDatetime": "2026-08-24T09:00:00+00:00",
                "startTime": "08:00",
                "endTime": "09:00",
                "reservedIntersection": True,  # should be excluded
            },
            {
                "courtName": "Court 1",
                "courtId": "c1",
                "slotId": "s4",
                "duration": 90,
                "price": 60.0,
                "startDatetime": "2026-08-24T09:00:00+00:00",
                "endDatetime": "2026-08-24T10:30:00+00:00",
                "startTime": "09:00",
                "endTime": "10:30",
                "reservedIntersection": False,
            },
        ]
    }

    req_meta = RequestDetailsWithMetadata(
        url="https://fastapi-production-fargate.padelmates.io/player/player_booking/all_courts_slot_prices_v2",
        headers={},
        payload=None,
        token=None,
        cookies=None,
        metadata=AdditionalRequestMetadata(
            category="Padel",
            date=date(2026, 8, 24),
            price=None,
            booking_url=f"{ORGANISATION_WEBSITE}/club/rocketpadelilford",
            sportsCentre=venue,
        ),
    )

    raw_response = RawResponseData(
        status_code=200,
        headers={},
        requestMetadata=req_meta,
        content=raw_content,
    )

    slots = parser.parse(raw_response)

    assert len(slots) == 2
    # In August (BST = UTC+1), 08:00:00 UTC is 09:00:00 BST
    slot_60 = [
        s
        for s in slots
        if (
            datetime.combine(date.min, s.ending_time)
            - datetime.combine(date.min, s.starting_time)
        ).seconds
        == 3600
    ][0]
    assert slot_60.spaces == 2
    assert slot_60.price == "£40.00"
    assert slot_60.composite_key == venue.composite_key
    assert slot_60.category == "Padel"

    slot_90 = [
        s
        for s in slots
        if (
            datetime.combine(date.min, s.ending_time)
            - datetime.combine(date.min, s.starting_time)
        ).seconds
        == 5400
    ][0]
    assert slot_90.spaces == 1
    assert slot_90.price == "£60.00"


def test_venue_fragment_definitions():
    fragment_path = (
        Path(__file__).parents[2] / "reports" / "venue-fragments" / "padelmates.json"
    )
    assert fragment_path.exists(), f"Fragment file not found at {fragment_path}"

    with open(fragment_path) as f:
        venues = json.load(f)

    assert isinstance(venues, list)
    assert len(venues) >= 5

    core_slugs = {
        "rocketpadelilford",
        "rocketpadelbattersea",
        "rocketpadelbeckton",
        "padium",
        "instantpadelatcanadawater",
    }

    found_slugs = set()
    for item in venues:
        assert item["organisation_website"] == ORGANISATION_WEBSITE
        slug = item["slug"]
        found_slugs.add(slug)
        assert item["sports"] == ["padel"]
        assert "postcode" in item["location"]
        assert "latitude" in item["location"]
        assert "longitude" in item["location"]
        assert item["location"]["latitude"] > 51.0

    assert core_slugs.issubset(found_slugs)
