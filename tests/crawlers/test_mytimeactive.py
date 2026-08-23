import json
from datetime import date, time
from pathlib import Path

from sportscanner.crawlers.parsers.core.schemas import (
    AdditionalRequestMetadata,
    RawResponseData,
    RequestDetailsWithMetadata,
)
from sportscanner.crawlers.parsers.mytimeactive.badminton.scraper import (
    MytimeActiveBadmintonRequestStrategy,
)
from sportscanner.crawlers.parsers.mytimeactive.core.strategy import (
    GLADSTONEGO_PORTAL_BASE,
    ORGANISATION_WEBSITE,
    GladstoneGoResponseParserStrategy,
)
from sportscanner.crawlers.parsers.mytimeactive.squash.scraper import (
    MytimeActiveSquashRequestStrategy,
)
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.storage.postgres.utils import generate_composite_key

ORGANISATION = "Mytime Active"


def _make_sports_venue(slug: str, name: str, sports: list[str]) -> SportsVenue:
    return SportsVenue(
        composite_key=generate_composite_key([ORGANISATION_WEBSITE, slug]),
        organisation=ORGANISATION,
        organisation_website=ORGANISATION_WEBSITE,
        venue_name=name,
        slug=slug,
        postcode="BR3 4PF" if slug == "SPA" else "BR6 0TJ",
        address="24 Beckenham Road" if slug == "SPA" else "Lych Gate Road",
        latitude=51.40905 if slug == "SPA" else 51.376983,
        longitude=-0.03785 if slug == "SPA" else 0.103137,
        sports=sports,
    )


def test_badminton_request_strategy():
    strategy = MytimeActiveBadmintonRequestStrategy()
    assert strategy.category == "Badminton"

    spa_venue = _make_sports_venue("SPA", "The Spa at Beckenham", ["badminton"])
    reqs_spa = strategy.generate_request_details(
        spa_venue, date(2026, 8, 24), token="mock_jwt"
    )

    assert len(reqs_spa) == 1
    req = reqs_spa[0]
    assert (
        req.url
        == f"{GLADSTONEGO_PORTAL_BASE}/api/availability/V2/sessions?siteIds=SPA&activityIDs=SPAACT0016&webBookableOnly=false&dateFrom=2026-08-24"
    )
    assert req.headers["x-use-sso"] == "1"
    assert req.headers["Cookie"] == "Jwt=mock_jwt"
    assert req.metadata.category == "Badminton"
    assert req.metadata.date == date(2026, 8, 24)
    assert (
        req.metadata.booking_url
        == f"{GLADSTONEGO_PORTAL_BASE}/book/calendar/SPAACT0016?activityDate=2026-08-24"
    )

    wal_venue = _make_sports_venue(
        "WAL", "The Walnuts Leisure Centre", ["badminton", "squash"]
    )
    reqs_wal = strategy.generate_request_details(wal_venue, date(2026, 8, 24))
    assert len(reqs_wal) == 1
    assert "activityIDs=WALACT0008" in reqs_wal[0].url

    unsupported_venue = _make_sports_venue("PAV", "The Pavilion", [])
    assert (
        len(strategy.generate_request_details(unsupported_venue, date(2026, 8, 24)))
        == 0
    )


def test_squash_request_strategy():
    strategy = MytimeActiveSquashRequestStrategy()
    assert strategy.category == "Squash"

    wal_venue = _make_sports_venue(
        "WAL", "The Walnuts Leisure Centre", ["badminton", "squash"]
    )
    reqs = strategy.generate_request_details(
        wal_venue, date(2026, 8, 24), token="mock_jwt"
    )

    assert len(reqs) == 1
    assert (
        reqs[0].url
        == f"{GLADSTONEGO_PORTAL_BASE}/api/availability/V2/sessions?siteIds=WAL&activityIDs=WALACT0009&webBookableOnly=false&dateFrom=2026-08-24"
    )
    assert reqs[0].metadata.category == "Squash"

    spa_venue = _make_sports_venue("SPA", "The Spa at Beckenham", ["badminton"])
    assert len(strategy.generate_request_details(spa_venue, date(2026, 8, 24))) == 0


def test_response_parsing():
    venue = _make_sports_venue("SPA", "The Spa at Beckenham", ["badminton"])
    parser = GladstoneGoResponseParserStrategy()

    raw_content = [
        {
            "id": "SPAACT0016",
            "name": "Badminton",
            "date": "2026-08-24",
            "siteId": "SPA",
            "webBookable": True,
            "slotCount": 2,
            "locations": [
                {
                    "locationNameToDisplay": "Court 1",
                    "slots": [
                        {
                            "startTime": "2026-08-24T06:00:00Z",
                            "endTime": "2026-08-24T06:59:59Z",
                            "availability": {"inCentre": 1, "virtual": 0},
                            "status": "Available",
                        },
                        {
                            "startTime": "2026-08-24T07:00:00Z",
                            "endTime": "2026-08-24T07:59:59Z",
                            "availability": {"inCentre": 0, "virtual": 0},
                            "status": "Unavailable",
                        },
                    ],
                },
                {
                    "locationNameToDisplay": "Court 2",
                    "slots": [
                        {
                            "startTime": "2026-08-24T06:00:00Z",
                            "endTime": "2026-08-24T06:59:59Z",
                            "availability": {"inCentre": 1, "virtual": 0},
                            "status": "Available",
                        },
                        {
                            "startTime": "2026-08-24T07:00:00Z",
                            "endTime": "2026-08-24T07:59:59Z",
                            "availability": {"inCentre": 0, "virtual": 0},
                            "status": "Unavailable",
                        },
                    ],
                },
            ],
        },
        {
            # Session for a different date to verify filtering
            "id": "SPAACT0016",
            "name": "Badminton",
            "date": "2026-08-25",
            "siteId": "SPA",
            "webBookable": True,
            "slotCount": 1,
            "locations": [
                {
                    "locationNameToDisplay": "Court 1",
                    "slots": [
                        {
                            "startTime": "2026-08-25T06:00:00Z",
                            "endTime": "2026-08-25T06:59:59Z",
                            "availability": {"inCentre": 1, "virtual": 0},
                            "status": "Available",
                        }
                    ],
                }
            ],
        },
    ]

    req_meta = RequestDetailsWithMetadata(
        url="https://mytimeactive.gladstonego.cloud/api/availability/V2/sessions?siteIds=SPA&activityIDs=SPAACT0016&webBookableOnly=false&dateFrom=2026-08-24",
        headers={},
        payload={},
        token=None,
        cookies=None,
        metadata=AdditionalRequestMetadata(
            category="Badminton",
            date=date(2026, 8, 24),
            price="",
            booking_url="https://mytimeactive.gladstonego.cloud/book/calendar/SPAACT0016?activityDate=2026-08-24",
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

    # Only 2 unique time slots for 2026-08-24
    assert len(slots) == 2
    # In August (BST = UTC+1), 06:00Z is 07:00 local time
    assert slots[0].category == "Badminton"
    assert slots[0].starting_time == time(7, 0)
    assert slots[0].ending_time == time(8, 0)
    assert slots[0].date == date(2026, 8, 24)
    # Aggregated across Court 1 and Court 2: 1 + 1 = 2 spaces
    assert slots[0].spaces == 2
    assert slots[0].composite_key == venue.composite_key

    # Second slot has 0 spaces
    assert slots[1].starting_time == time(8, 0)
    assert slots[1].ending_time == time(9, 0)
    assert slots[1].spaces == 0


def test_venue_fragment_definitions():
    fragment_path = (
        Path(__file__).parents[2]
        / "reports"
        / "venue-fragments"
        / "mytimeactive.json"
    )
    assert fragment_path.exists(), f"Fragment file not found at {fragment_path}"

    with open(fragment_path) as f:
        data = json.load(f)

    assert isinstance(data, dict)
    assert data["organisation"] == ORGANISATION
    assert data["organisation_website"] == ORGANISATION_WEBSITE
    venues = data["venues"]
    assert len(venues) == 2

    expected_venues = {
        "SPA": {"name": "The Spa at Beckenham", "sports": ["badminton"]},
        "WAL": {
            "name": "The Walnuts Leisure Centre",
            "sports": ["badminton", "squash"],
        },
    }

    for v in venues:
        slug = v["slug"]
        assert slug in expected_venues
        assert v["venue_name"] == expected_venues[slug]["name"]
        assert v["sports"] == expected_venues[slug]["sports"]
        assert "postcode" in v["location"]
        assert "latitude" in v["location"]
        assert "longitude" in v["location"]
        assert v["location"]["latitude"] > 51.0
        assert -0.1 <= v["location"]["longitude"] <= 0.2
