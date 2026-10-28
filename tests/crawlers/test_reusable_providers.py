import json
from datetime import date, time
from pathlib import Path

from sportscanner.crawlers.parsers.clubspark.core.strategy import (
    ClubSparkPadelResponseParserStrategy,
    is_padel_resource,
)
from sportscanner.crawlers.parsers.core.schemas import (
    AdditionalRequestMetadata,
    RawResponseData,
    RequestDetailsWithMetadata,
)
from sportscanner.crawlers.parsers.gladstonego.core.venues import (
    GLADSTONE_TENANTS,
)
from sportscanner.crawlers.parsers.matchpoint.core.venues import (
    MATCHPOINT_TENANTS,
)
from sportscanner.crawlers.parsers.padelmates.core.strategy import (
    CLUB_SLUG_TO_CLUB_ID,
)
from sportscanner.storage.postgres.tables import SportsVenue

REPO = Path(__file__).parents[2]
VENUES = json.loads((REPO / "sportscanner" / "venues.json").read_text())


def venue(slug: str, website: str, sports: list[str] | None = None) -> SportsVenue:
    return SportsVenue(
        composite_key="00000000",
        organisation="test",
        organisation_website=website,
        venue_name=slug,
        slug=slug,
        postcode="SW1A 1AA",
        address="test",
        latitude=51.5,
        longitude=-0.1,
        sports=sports or ["padel"],
    )


def test_is_padel_resource_is_explicit():
    assert is_padel_resource("Padel Court 1", 13)
    assert is_padel_resource("NTC Padel court 1", 1)
    assert not is_padel_resource("Tennis Court 1", 1)
    assert not is_padel_resource("Padel Equipment locker 1", 13)
    assert not is_padel_resource("Pickleball Court", 14)


def test_clubspark_padel_parser_never_emits_tennis():
    parser = ClubSparkPadelResponseParserStrategy()
    sports_venue = venue("BroughtonPadel", "https://clubspark.lta.org.uk")
    request = RequestDetailsWithMetadata(
        url="https://clubspark.lta.org.uk/v0/VenueBooking/BroughtonPadel/GetVenueSessions",
        headers={},
        metadata=AdditionalRequestMetadata(
            category="Padel",
            date=date(2026, 10, 29),
            sportsCentre=sports_venue,
        ),
    )
    response = RawResponseData(
        status_code=200,
        headers={},
        requestMetadata=request,
        content={
            "Resources": [
                {
                    "ID": "1",
                    "Name": "Padel Court 1",
                    "Category": 13,
                    "Location": 0,
                    "Days": [
                        {
                            "Date": "2026-10-29T00:00:00",
                            "Sessions": [
                                {
                                    "Category": 1000,
                                    "Name": "Booking",
                                    "StartTime": 480,
                                    "EndTime": 540,
                                    "CourtCost": 20.0,
                                }
                            ],
                        }
                    ],
                },
                {
                    "ID": "2",
                    "Name": "Tennis Court 1",
                    "Category": 1,
                    "Days": [
                        {
                            "Date": "2026-10-29T00:00:00",
                            "Sessions": [
                                {
                                    "Category": 1000,
                                    "Name": "Booking",
                                    "StartTime": 480,
                                    "EndTime": 540,
                                    "CourtCost": 10.0,
                                }
                            ],
                        }
                    ],
                },
            ]
        },
    )
    slots = parser.parse(response)
    assert len(slots) == 1
    assert slots[0].category == "Padel"
    assert slots[0].starting_time == time(8, 0)
    assert slots[0].ending_time == time(9, 0)


def _organisation_venues(name: str) -> list[dict]:
    return next(org["venues"] for org in VENUES if org["organisation"] == name)


def test_new_provider_mappings_reconcile_with_venues_json():
    assert {v["slug"] for v in _organisation_venues("Matchpoint")} <= set(
        MATCHPOINT_TENANTS
    )
    gladstone_venues = {v["slug"] for v in _organisation_venues("Gladstone Go")}
    assert gladstone_venues <= set(GLADSTONE_TENANTS)
    for slug in gladstone_venues:
        assert GLADSTONE_TENANTS[slug]["activity_ids"]


def test_stale_dagenham_entry_is_removed():
    all_slugs = {v["slug"] for org in VENUES for v in org["venues"]}
    assert "playtimepadeldagenham" not in all_slugs
    assert "playtimepadeldagenham" not in CLUB_SLUG_TO_CLUB_ID
    assert CLUB_SLUG_TO_CLUB_ID["playtimepadelbarking"] == (
        "9c605bfae8494a34bef3910eb770e427"
    )
