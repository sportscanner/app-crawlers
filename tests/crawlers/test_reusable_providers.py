import json
from datetime import date, time
from pathlib import Path

from sportscanner.crawlers.parsers.clubspark.core.strategy import (
    ClubSparkPadelResponseParserStrategy,
    ClubSparkTennisResponseParserStrategy,
    is_padel_resource,
    is_tennis_resource,
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


def test_is_tennis_resource_excludes_other_sports():
    assert is_tennis_resource("Court 1", 1)
    assert is_tennis_resource("Mini Court 1", 2)
    assert is_tennis_resource("Walking Tennis 1", 33)
    assert not is_tennis_resource("Padel Court 1", 1)
    assert not is_tennis_resource("Pickleball 1", 14)
    assert not is_tennis_resource("Netball 1", 12)
    assert not is_tennis_resource("Community Room", 38)
    assert not is_tennis_resource("Coaching", 11)


def _clubspark_request(category: str, slug: str) -> RequestDetailsWithMetadata:
    return RequestDetailsWithMetadata(
        url=f"https://clubspark.lta.org.uk/v0/VenueBooking/{slug}/GetVenueSessions",
        headers={},
        metadata=AdditionalRequestMetadata(
            category=category,
            date=date(2026, 10, 29),
            sportsCentre=venue(slug, "https://clubspark.lta.org.uk"),
        ),
    )


def test_clubspark_tennis_parser_uses_available_sessions_only():
    parser = ClubSparkTennisResponseParserStrategy()
    request = _clubspark_request("Tennis", "OldDeerPark")
    response = RawResponseData(
        status_code=200,
        headers={},
        requestMetadata=request,
        content={
            "Resources": [
                {
                    "ID": "court-1",
                    "Name": "Court 1",
                    "Category": 1,
                    "Location": 0,
                    "Days": [
                        {
                            "Date": "2026-10-29T00:00:00",
                            "Sessions": [
                                # Available 06:00-08:00, minimum interval 60:
                                # two real bookable slots.
                                {
                                    "Category": 0,
                                    "Name": "Default",
                                    "StartTime": 360,
                                    "EndTime": 480,
                                    "Interval": 60,
                                    "Capacity": 1,
                                    "CostFrom": 5.7,
                                    "CourtCost": 5.7,
                                },
                                # Existing booking, including a recurring
                                # block total. Must never become availability.
                                {
                                    "Category": 1000,
                                    "Name": "Booking",
                                    "StartTime": 840,
                                    "EndTime": 900,
                                    "Interval": 60,
                                    "Capacity": 0,
                                    "CourtCost": 820.8,
                                    "Recurrence": True,
                                },
                            ],
                        }
                    ],
                },
                {
                    "ID": "court-2",
                    "Name": "Court 2",
                    "Category": 1,
                    "Location": 0,
                    "Days": [
                        {
                            "Date": "2026-10-29T00:00:00",
                            "Sessions": [
                                # Category 0 but role-restricted (staff/member
                                # only): not public availability, even at £0.
                                {
                                    "Category": 0,
                                    "Name": "Restricted",
                                    "Restrictions": "Administrator, NTC Front of House",
                                    "StartTime": 360,
                                    "EndTime": 420,
                                    "Interval": 60,
                                    "Capacity": 1,
                                    "CourtCost": 0.0,
                                }
                            ],
                        }
                    ],
                },
                {
                    "ID": "room-1",
                    "Name": "Community Room",
                    "Category": 38,
                    "Location": 1,
                    "Days": [
                        {
                            "Date": "2026-10-29T00:00:00",
                            "Sessions": [
                                {
                                    "Category": 0,
                                    "Name": "Default",
                                    "StartTime": 360,
                                    "EndTime": 420,
                                    "Interval": 60,
                                    "Capacity": 1,
                                    "CourtCost": 0.0,
                                }
                            ],
                        }
                    ],
                },
            ]
        },
    )

    slots = parser.parse(response)

    assert [(s.starting_time, s.ending_time, s.price, s.spaces) for s in slots] == [
        (time(6, 0), time(7, 0), "£5.70", 1),
        (time(7, 0), time(8, 0), "£5.70", 1),
    ]


def test_clubspark_tennis_parser_splits_at_venue_minimum_interval():
    parser = ClubSparkTennisResponseParserStrategy()
    request = _clubspark_request("Tennis", "OldDeerPark")
    response = RawResponseData(
        status_code=200,
        headers={},
        requestMetadata=request,
        content={
            "MinimumInterval": 30,
            "Resources": [
                {
                    "ID": "court-1",
                    "Name": "Court 1",
                    "Category": 1,
                    "Location": 0,
                    "Days": [
                        {
                            "Date": "2026-10-29T00:00:00",
                            "Sessions": [
                                {
                                    "Category": 0,
                                    "Name": "Default",
                                    "StartTime": 360,
                                    "EndTime": 420,
                                    "Interval": 60,
                                    "Capacity": 1,
                                    "CostFrom": 5.7,
                                    "CourtCost": 5.7,
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )

    slots = parser.parse(response)

    assert [(s.starting_time, s.ending_time, s.price) for s in slots] == [
        (time(6, 0), time(6, 30), "£5.70"),
        (time(6, 30), time(7, 0), "£5.70"),
    ]


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
                                    "Category": 0,
                                    "Name": "Default",
                                    "StartTime": 480,
                                    "EndTime": 540,
                                    "Interval": 60,
                                    "Capacity": 1,
                                    "CostFrom": 20.0,
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
                                    "Category": 0,
                                    "Name": "Default",
                                    "StartTime": 480,
                                    "EndTime": 540,
                                    "Interval": 60,
                                    "Capacity": 1,
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
