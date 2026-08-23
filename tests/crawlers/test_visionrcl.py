from datetime import date, time
import json
from pathlib import Path

from sportscanner.crawlers.parsers.better.core.strategy import (
    BetterLeisureResponseParserStrategy,
)
from sportscanner.crawlers.parsers.core.schemas import (
    AdditionalRequestMetadata,
    RawResponseData,
    RequestDetailsWithMetadata,
    UnifiedParserSchema,
)
from sportscanner.crawlers.parsers.visionrcl.badminton.scraper import (
    VisionRclBadmintonCrawler,
    VisionRclBadmintonRequestStrategy,
)
from sportscanner.crawlers.parsers.visionrcl.core.strategy import (
    TENANT_BOOKING_HOST,
    VisionRclRequestStrategy,
)
from sportscanner.crawlers.parsers.visionrcl.squash.scraper import (
    VisionRclSquashCrawler,
    VisionRclSquashRequestStrategy,
)
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.storage.postgres.utils import generate_composite_key

ORGANISATION = "Vision RCL"
ORGANISATION_WEBSITE = "https://www.visionrcl.org.uk"


def _make_sports_venue(slug: str, name: str, sports: list[str]) -> SportsVenue:
    return SportsVenue(
        composite_key=generate_composite_key([ORGANISATION_WEBSITE, slug]),
        organisation=ORGANISATION,
        organisation_website=ORGANISATION_WEBSITE,
        venue_name=name,
        slug=slug,
        postcode="E11 2JZ",
        address="Redbridge Lane West, Wanstead, E11 2JZ",
        latitude=51.575655,
        longitude=0.035762,
        sports=sports,
    )


def test_badminton_request_strategy():
    strategy = VisionRclBadmintonRequestStrategy()
    assert strategy.activity_slugs == ["badminton/v2"]
    assert strategy.category == "Badminton"

    venue = _make_sports_venue(
        "wanstead-leisure-centre", "Wanstead Leisure Centre", ["badminton", "squash"]
    )
    reqs = strategy.generate_request_details(venue, date(2026, 8, 24))

    assert len(reqs) == 1
    req = reqs[0]
    assert req.url == "https://flow.onl/api/activities/venue/wanstead-leisure-centre/activity/badminton/v2/times?date=2026-08-24"
    assert req.headers["origin"] == TENANT_BOOKING_HOST
    assert "wanstead-leisure-centre" in req.headers["referer"]
    assert req.metadata.category == "Badminton"
    assert req.metadata.date == date(2026, 8, 24)
    assert req.metadata.booking_url == "https://vision.bookings.flow.onl/location/wanstead-leisure-centre/badminton/v2/2026-08-24/by-time/"


def test_squash_request_strategy():
    strategy = VisionRclSquashRequestStrategy()
    assert strategy.activity_slugs == ["squash-60/v2", "squash-45/v2"]
    assert strategy.category == "Squash"

    venue = _make_sports_venue(
        "wanstead-leisure-centre", "Wanstead Leisure Centre", ["badminton", "squash"]
    )
    reqs = strategy.generate_request_details(venue, date(2026, 8, 24))

    assert len(reqs) == 2
    slugs = [r.metadata.booking_url for r in reqs]
    assert any("squash-60/v2" in url for url in slugs)
    assert any("squash-45/v2" in url for url in slugs)


def test_response_parsing():
    venue = _make_sports_venue(
        "wanstead-leisure-centre", "Wanstead Leisure Centre", ["badminton", "squash"]
    )
    parser = BetterLeisureResponseParserStrategy()

    raw_content = [
        {
            "starts_at": {"format_12_hour": "09:30am", "format_24_hour": "09:30"},
            "ends_at": {"format_12_hour": "10:30am", "format_24_hour": "10:30"},
            "duration": "60min",
            "price": {"is_estimated": True, "formatted_amount": "£13.50"},
            "category_slug": "badminton",
            "date": "2026-08-24",
            "venue_slug": "wanstead-leisure-centre",
            "composite_key": "f99a84b1",
            "spaces": 5,
            "name": "Badminton",
            "allows_anonymous_bookings": False,
        },
        {
            "starts_at": {"format_12_hour": "10:30am", "format_24_hour": "10:30"},
            "ends_at": {"format_12_hour": "11:30am", "format_24_hour": "11:30"},
            "duration": "60min",
            "price": {"is_estimated": True, "formatted_amount": "£13.50"},
            "category_slug": "badminton",
            "date": "2026-08-24",
            "venue_slug": "wanstead-leisure-centre",
            "composite_key": "f99a84b1",
            "spaces": 0,
            "name": "Badminton",
            "allows_anonymous_bookings": False,
        },
    ]

    req_meta = RequestDetailsWithMetadata(
        url="https://flow.onl/api/activities/venue/wanstead-leisure-centre/activity/badminton/v2/times?date=2026-08-24",
        headers={},
        payload={},
        token=None,
        cookies=None,
        metadata=AdditionalRequestMetadata(
            category="Badminton",
            date=date(2026, 8, 24),
            price=None,
            booking_url="https://vision.bookings.flow.onl/location/wanstead-leisure-centre/badminton/v2/2026-08-24/by-time/",
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
    assert slots[0].category == "Badminton"
    assert slots[0].starting_time == time(9, 30)
    assert slots[0].ending_time == time(10, 30)
    assert slots[0].date == date(2026, 8, 24)
    assert slots[0].price == "£13.50"
    assert slots[0].spaces == 5
    assert slots[0].composite_key == venue.composite_key

    assert slots[1].spaces == 0


def test_venue_fragment_definitions():
    fragment_path = Path(__file__).parents[2] / "reports" / "venue-fragments" / "visionrcl.json"
    assert fragment_path.exists(), f"Fragment file not found at {fragment_path}"

    with open(fragment_path) as f:
        venues = json.load(f)

    assert isinstance(venues, list)
    assert len(venues) == 3

    expected_slugs = {
        "loxford-leisure-centre": ["badminton"],
        "wanstead-leisure-centre": ["badminton", "squash"],
        "mayfield-leisure-centre": ["badminton"],
    }

    for item in venues:
        assert item["organisation"] == ORGANISATION
        assert item["organisation_website"] == ORGANISATION_WEBSITE
        slug = item["slug"]
        assert slug in expected_slugs
        assert item["sports"] == expected_slugs[slug]
        assert "postcode" in item["location"]
        assert "latitude" in item["location"]
        assert "longitude" in item["location"]
        assert item["location"]["latitude"] > 51.0
        assert item["location"]["longitude"] >= 0.0
