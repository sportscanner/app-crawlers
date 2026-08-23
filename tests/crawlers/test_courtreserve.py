from datetime import date, datetime, time
from zoneinfo import ZoneInfo
import pytest

from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.courtreserve.core.schema import (
    CourtReserveCalendarEventSchema,
)
from sportscanner.crawlers.parsers.courtreserve.core.strategy import (
    COURTRESERVE_ORGANISATION_WEBSITE,
    VENUE_KEY_TO_SLUG,
    build_calendar_read_payload,
    normalise_title,
    parse_calendar_events,
    parse_courtreserve_epoch_ms,
    spaces_from_event,
    venue_slug_from_event_title,
)
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.storage.postgres.utils import generate_composite_key


def test_venue_slug_matching():
    assert venue_slug_from_event_title("Social Play - Hampstead") == "hampstead"
    assert (
        venue_slug_from_event_title("Social Play - Highgate - Outdoors")
        == "highgate-outdoors"
    )
    assert venue_slug_from_event_title("Social Play - Highgate") == "highgate"
    assert (
        venue_slug_from_event_title("Drils - Highgate - Indoors - Red Ball")
        == "highgate-indoors-red-ball"
    )
    assert (
        venue_slug_from_event_title("Social Play Early Improver - Finchley Outdoors")
        == "finchley-outdoors"
    )
    assert (
        venue_slug_from_event_title("3 Week Beginners Course - Finchley") == "finchley"
    )
    assert (
        venue_slug_from_event_title("Summer Camp Week 6 - Christ's College Finchley")
        == "christs-college-finchley"
    )
    assert (
        venue_slug_from_event_title(
            "Early Improver Group Lesson - East Finchley - Bishop Douglass"
        )
        == "east-finchley-bishop-douglass"
    )
    assert venue_slug_from_event_title("Social Play - East Finchley") == "east-finchley"
    assert (
        venue_slug_from_event_title("DUPR Doubles Session - North Finchley")
        == "north-finchley"
    )
    assert (
        venue_slug_from_event_title("Intermediate - Westway Tennis Centre")
        == "westway-tennis-centre"
    )
    assert venue_slug_from_event_title("Social Play - Enfield") == "enfield"
    assert venue_slug_from_event_title("Social Play - Farringdon") == "farringdon"
    assert venue_slug_from_event_title("Social play - Hackney") == "hackney"
    assert venue_slug_from_event_title("Social Play - Hoxton") == "hoxton"
    assert (
        venue_slug_from_event_title(
            "Autumn Term Junior Club for 7-13 year olds - Kentish Town"
        )
        == "kentish-town"
    )
    assert venue_slug_from_event_title("Social Play - Maida Vale") == "maida-vale"
    assert venue_slug_from_event_title("Social Play - Marylebone") == "marylebone"
    assert venue_slug_from_event_title("Social Play - Muswell Hill") == "muswell-hill"
    assert venue_slug_from_event_title("Lemon Pickleball Squad League") is None
    assert venue_slug_from_event_title("3rd Anniversary Party") is None


def test_epoch_parsing():
    dt = parse_courtreserve_epoch_ms("/Date(1787470200000)/")
    assert dt.tzinfo == ZoneInfo("UTC")
    assert dt.year >= 2026

    with pytest.raises(ValueError):
        parse_courtreserve_epoch_ms("invalid-epoch")


def test_spaces_from_event():
    # Active open event with remaining spots
    ev_open = CourtReserveCalendarEventSchema(
        Title="Social Play - Hampstead",
        EventName="Social Play - Hampstead",
        Number="EV1",
        Start="/Date(1787470200000)/",
        End="/Date(1787473800000)/",
        MaxMembersOnEvent=16,
        SignedMembers=6,
        IsFull=False,
        InPast=False,
    )
    assert spaces_from_event(ev_open) == 10

    # Full event
    ev_full = CourtReserveCalendarEventSchema(
        Title="Social Play - Hampstead",
        EventName="Social Play - Hampstead",
        Number="EV2",
        Start="/Date(1787470200000)/",
        End="/Date(1787473800000)/",
        MaxMembersOnEvent=16,
        SignedMembers=16,
        IsFull=True,
        InPast=False,
    )
    assert spaces_from_event(ev_full) == 0

    # Past event
    ev_past = CourtReserveCalendarEventSchema(
        Title="Social Play - Hampstead",
        EventName="Social Play - Hampstead",
        Number="EV3",
        Start="/Date(1787470200000)/",
        End="/Date(1787473800000)/",
        MaxMembersOnEvent=16,
        SignedMembers=2,
        IsFull=False,
        InPast=True,
    )
    assert spaces_from_event(ev_past) == 0


def test_build_calendar_read_payload():
    d = date(2026, 8, 24)
    payload = build_calendar_read_payload(d)
    assert "jsonData" in payload
    import json

    data = json.loads(payload["jsonData"])
    assert data["orgId"] == "13469"
    assert data["KendoStart"] == {"Year": 2026, "Month": 8, "Day": 24}
    assert data["KendoEnd"] == {"Year": 2026, "Month": 8, "Day": 24}


def test_parse_calendar_events():
    venue = SportsVenue(
        composite_key=generate_composite_key(
            [COURTRESERVE_ORGANISATION_WEBSITE, "hampstead"]
        ),
        organisation="Lemon Pickleball",
        organisation_website=COURTRESERVE_ORGANISATION_WEBSITE,
        venue_name="Hampstead",
        slug="hampstead",
        postcode="NW3 2QG",
        address="Fleet Rd, London NW3 2QG",
        latitude=51.553227,
        longitude=-0.165298,
        sports=["pickleball"],
    )
    slug_to_venue = {"hampstead": venue}

    raw_events = [
        {
            "Title": "Social Play - Hampstead",
            "EventName": "Social Play - Hampstead",
            "Number": "ABC123",
            "Start": "/Date(1787470200000)/",
            "End": "/Date(1787475600000)/",
            "MaxMembersOnEvent": 12,
            "SignedMembers": 4,
            "IsFull": False,
            "InPast": False,
        },
        {
            "Title": "Unmatched Event Without Venue",
            "EventName": "Unmatched Event Without Venue",
            "Number": "SKIP1",
            "Start": "/Date(1787470200000)/",
            "End": "/Date(1787475600000)/",
            "MaxMembersOnEvent": 12,
            "SignedMembers": 4,
            "IsFull": False,
            "InPast": False,
        },
    ]

    slots = parse_calendar_events(raw_events, slug_to_venue, category="Pickleball")
    assert len(slots) == 1
    slot = slots[0]
    assert isinstance(slot, UnifiedParserSchema)
    assert slot.category == "Pickleball"
    assert slot.spaces == 8
    assert slot.composite_key == venue.composite_key
    assert slot.price == "N/A"
    assert (
        slot.booking_url
        == "https://app.courtreserve.com/Online/Events/Details/13469/ABC123"
    )
    assert isinstance(slot.starting_time, time)
    assert isinstance(slot.ending_time, time)
    assert isinstance(slot.date, date)
