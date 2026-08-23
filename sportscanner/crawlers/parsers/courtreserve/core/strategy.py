"""CourtReserve public-portal request/parse logic (Lemon Pickleball, orgId 13469).

Endpoint discovery (August 2026): the portal shell at
https://app.courtreserve.com/Online/Portal/Index/13469 is an MVC page whose
"Session Calendar" tab (customId=73838) embeds a Kendo Scheduler. Its read
transport is a plain anonymous POST:

    POST https://app.courtreserve.com/Online/Calendar/ReadCalendarEvents/13469
    Content-Type: application/x-www-form-urlencoded
    Body: jsonData={"startDate": "...", "end": "...", "orgId": "13469", ...}

No cookies, no auth header, no per-page encrypted requestData token needed
(those tokens exist on other portal endpoints but this one answers without).
Court reservations (/Online/Reservations/Index/13469) and the events listing
(/Online/EventsApi/ApiList) are both login-gated for this org - only this
calendar read is public, which is why the crawler is built around it.

Dates: KendoStart/KendoEnd mirror startDate/end as {Year, Month, Day} objects
(the page's getKendoStart/getKendoEnd). Start/End epoch millis in the response
are UTC; session times displayed on the portal are Europe/London, so the
parser converts with zoneinfo before splitting into date + start/end times.
"""

import json
import re
from datetime import date, datetime, time
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.courtreserve.core.schema import (
    CourtReserveCalendarEventSchema,
)
from sportscanner.logger import logging

COURTRESERVE_ORG_ID = "13469"  # Lemon Pickleball
COURTRESERVE_ORGANISATION_WEBSITE = "https://lemonpickleball.com"
COURTRESERVE_CALENDAR_READ_URL = f"https://app.courtreserve.com/Online/Calendar/ReadCalendarEvents/{COURTRESERVE_ORG_ID}"
COURTRESERVE_BOOKING_URL_TEMPLATE = f"https://app.courtreserve.com/Online/Events/Details/{COURTRESERVE_ORG_ID}/{{number}}"

LONDON_TZ = ZoneInfo("Europe/London")

# Venue names are embedded at the tail of session titles, e.g.
# "Social Play - Highgate - Outdoors" or "Drils - Highgate - Indoors - Red Ball".
# Match longest-first so "Highgate - Outdoors" wins over plain "Highgate", and
# "North Finchley"/"East Finchley"/"Christ's College Finchley" win over "Finchley".
# Keys are matched case-insensitively against the whitespace-normalised title.
VENUE_KEY_TO_SLUG: List[Tuple[str, str]] = [
    ("highgate - indoors - red ball", "highgate-indoors-red-ball"),
    ("east finchley - bishop douglass", "east-finchley-bishop-douglass"),
    ("christ's college finchley", "christs-college-finchley"),
    ("highgate - outdoors", "highgate-outdoors"),
    ("finchley outdoors", "finchley-outdoors"),
    ("westway tennis centre", "westway-tennis-centre"),
    ("kentish town", "kentish-town"),
    ("muswell hill", "muswell-hill"),
    ("maida vale", "maida-vale"),
    ("north finchley", "north-finchley"),
    ("east finchley", "east-finchley"),
    ("marylebone", "marylebone"),
    ("hampstead", "hampstead"),
    ("highgate", "highgate"),
    ("farringdon", "farringdon"),
    ("hackney", "hackney"),
    ("hoxton", "hoxton"),
    ("enfield", "enfield"),
    ("finchley", "finchley"),
]

_EPOCH_MS_PATTERN = re.compile(r"/Date\((\d+)\)/")


def normalise_title(title: str) -> str:
    return " ".join(title.lower().split())


def venue_slug_from_event_title(title: str) -> Optional[str]:
    """Longest-first substring match of the venue name inside a session title."""
    normalized = normalise_title(title)
    for venue_key, slug in VENUE_KEY_TO_SLUG:
        if venue_key in normalized:
            return slug
    return None


def parse_courtreserve_epoch_ms(raw: str) -> datetime:
    """Parse a Kendo/ASP.NET "/Date(1787470200000)/" string into a UTC datetime."""
    match = _EPOCH_MS_PATTERN.match(raw)
    if not match:
        raise ValueError(f"Unrecognised CourtReserve date format: {raw!r}")
    return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=ZoneInfo("UTC"))


def build_calendar_read_payload(
    fetch_date: date, org_id: str = COURTRESERVE_ORG_ID
) -> Dict[str, str]:
    """Form body replicating the Kendo scheduler's read request for one day."""
    criteria = {
        "startDate": f"{fetch_date.isoformat()}T00:00:00.000Z",
        "end": f"{fetch_date.isoformat()}T00:00:00.000Z",
        "Date": fetch_date.strftime("%a, %d %b %Y 00:00:00 GMT"),
        "orgId": org_id,
        "TimeZone": "Europe/London",
        "KendoStart": {
            "Year": fetch_date.year,
            "Month": fetch_date.month,
            "Day": fetch_date.day,
        },
        "KendoEnd": {
            "Year": fetch_date.year,
            "Month": fetch_date.month,
            "Day": fetch_date.day,
        },
        "Categories": [],
        "EventTagIds": [],
        "CostTypeId": "",
        "MemberId": "",
        "FamilyId": "",
        "FamilyMemberIds": "",
        "EventSessionIds": [],
        "ViewType": "Month",
        "MonthlySelectedDate": "",
        "IsLeagueCalendar": "False",
        "IncludeLeagues": "True",
        "IncludeRoundRobins": "False",
    }
    return {"jsonData": json.dumps(criteria)}


def spaces_from_event(event: CourtReserveCalendarEventSchema) -> int:
    """Bookable spots remaining: capacity minus sign-ups, floored at 0.
    Past occurrences and full sessions report 0 (spaces = 0 is the
    codebase-wide "unavailable" signal)."""
    if event.InPast or event.IsFull:
        return 0
    return max(event.MaxMembersOnEvent - event.SignedMembers, 0)


def parse_calendar_events(
    events: List[dict],
    slug_to_venue,
    category: str = "Pickleball",
) -> List[UnifiedParserSchema]:
    """Map raw calendar rows to UnifiedParserSchema for the given venues.

    slug_to_venue: mapping of venue slug -> SportsVenue row (from the DB).
    Rows whose title matches no requested venue are skipped (other providers'
    sessions, org-wide socials, leagues without a venue suffix).
    """
    parsed: List[UnifiedParserSchema] = []
    skipped_unmatched = 0
    for row in events:
        try:
            event = CourtReserveCalendarEventSchema(**row)
        except Exception as e:
            logging.warning(f"CourtReserve: skipping malformed calendar row: {e}")
            continue
        slug = venue_slug_from_event_title(event.EventName)
        if slug is None or slug not in slug_to_venue:
            skipped_unmatched += 1
            continue
        venue = slug_to_venue[slug]
        start_utc = parse_courtreserve_epoch_ms(event.Start)
        end_utc = parse_courtreserve_epoch_ms(event.End)
        start_local = start_utc.astimezone(LONDON_TZ)
        end_local = end_utc.astimezone(LONDON_TZ)
        parsed.append(
            UnifiedParserSchema(
                category=category,
                starting_time=start_local.time().replace(tzinfo=None),
                ending_time=end_local.time().replace(tzinfo=None),
                date=start_local.date(),
                price="N/A",
                spaces=spaces_from_event(event),
                composite_key=venue.composite_key,
                last_refreshed=datetime.now(),
                booking_url=COURTRESERVE_BOOKING_URL_TEMPLATE.format(
                    number=event.Number
                ),
            )
        )
    if skipped_unmatched:
        logging.debug(
            f"CourtReserve: skipped {skipped_unmatched} calendar rows with no matching venue"
        )
    return parsed
