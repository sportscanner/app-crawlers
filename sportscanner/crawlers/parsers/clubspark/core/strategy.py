"""
ClubSpark (LTA) strategy implementations.

GetVenueSessions is an unauthenticated public JSON endpoint (confirmed live,
no auth headers/cookies required) that returns every court's session grid for
a venue across a startDate/endDate range in one call:

    GET https://clubspark.lta.org.uk/v0/VenueBooking/{VenueSlug}/GetVenueSessions
        ?resourceID=&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&roleId=

Each session has a `Category`: 0 = genuinely available to book, 1000 = an
existing booking, 2000 = coaching/programmed, 8000 = closed. Only Category 0
rows are real availability. Category 0 sessions are continuous windows and
must be split by the response's `MinimumInterval` into bookable slots. Venue slugs must be verified
via the companion `GetSettings`
endpoint before use — guessed slugs (e.g. from a park's common name) 404
silently rather than falling back to anything useful.
"""

import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, Coroutine, Dict, List, Optional

from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.clubspark.core.schema import (
    ClubSparkVenueSessionsResponse,
)
from sportscanner.crawlers.parsers.core.interfaces import (
    AbstractRequestStrategy,
    AbstractResponseParserStrategy,
)
from sportscanner.crawlers.parsers.core.schemas import (
    AdditionalRequestMetadata,
    RawResponseData,
    RequestDetailsWithMetadata,
    UnifiedParserSchema,
)
from sportscanner.logger import logging
from sportscanner.storage.postgres.tables import SportsVenue

CLUBSPARK_ORGANISATION_WEBSITE = "https://clubspark.lta.org.uk"

# Session-level Category (not the resource's sport Category):
#   0    = genuinely available to book
#   1000 = already booked / an existing booking
#   2000 = coaching or programmed session
#   8000 = closed
# Only Category 0 is availability. The response shape was confirmed live
# 2026-10-31 against Old Deer Park and Battersea Park: available sessions
# carry Capacity=1 and a non-zero CostFrom; booked sessions carry Capacity=0
# and a person/event name ("Booking", "Penny", "Netball - 4 Courts").
AVAILABLE_CATEGORY = 0
PADEL_CATEGORY = 13
TENNIS_RESOURCE_CATEGORIES = {1, 2, 3, 33}
_PADEL_EXCLUDED_RE = re.compile(
    r"equipment|locker|racket|racquet|ball machine|machine", re.I
)
_TENNIS_EXCLUDED_RE = re.compile(
    r"padel|pickleball|netball|football|cricket|community|coaching|athletics|hockey|rugby",
    re.I,
)


def is_padel_resource(name: str, category: Optional[int]) -> bool:
    """Whether a ClubSpark resource is a padel court.

    Category 13 is the API's own Padel category. A handful of venues (notably
    the LTA's dedicated PadelNTC account) file their padel courts under the
    tennis category, so an explicit "padel" in the resource name is also
    accepted -- but a resource merely called "Tennis Court" never is.
    Equipment lockers are Category 13 on some sites and must be excluded.
    """
    if _PADEL_EXCLUDED_RE.search(name or ""):
        return False
    if category == PADEL_CATEGORY:
        return True
    return "padel" in (name or "").lower()


def is_tennis_resource(name: str, category: Optional[int]) -> bool:
    """Whether a ClubSpark resource is a tennis court.

    ClubSpark exposes every bookable resource at a multi-sport venue through
    the same GetVenueSessions call (tennis, padel, netball, cricket nets, a
    community room...). Resource Category 1 is tennis; 2/3/33 are mini, touch
    and walking tennis. Only those courts belong in the tennis table. When a
    venue omits Category, fall back to a name check, still rejecting the other
    sports/facilities that share a ClubSpark site.
    """
    if _TENNIS_EXCLUDED_RE.search(name or ""):
        return False
    if category in TENNIS_RESOURCE_CATEGORIES:
        return True
    if category is not None:
        return False
    lowered = (name or "").lower()
    return "tennis" in lowered or "court" in lowered


def _minutes_to_time(minutes: int) -> time:
    return (datetime.min + timedelta(minutes=minutes)).time()

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


def referer_for_slug(slug: str) -> str:
    # GetVenueSessions 403s (Cloudflare bot management) unless the request
    # carries a Referer from the venue's own booking page -- confirmed live
    # August 2026: identical request without Referer gets 403, with it gets
    # 200. This was almost certainly the real cause of the intermittent
    # whole-run 403s previously attributed purely to IP reputation.
    return f"{CLUBSPARK_ORGANISATION_WEBSITE}/{slug}/Booking/BookByDate"


# Venues whose "/Booking/BookByDate" page server-side redirects (302) to LTA
# Play login (".../{slug}/Booking/LTAPlayLogin") instead of showing the
# availability calendar anonymously. Confirmed venue by venue, August 2026,
# across all 49 London venues in venues.json via curl_cffi chrome impersonation
# (plain curl sees the same 302, so this is ClubSpark's own routing, not a
# Cloudflare artifact). Their underlying GetVenueSessions JSON API still serves
# real availability anonymously, so these venues stay in scope - only the deep
# customer-facing link is gated. For these, booking_url points at the venue's
# public home page instead, which loads fine without an account and links out
# to booking.
_LOGIN_GATED_BOOKING_PAGE_SLUGS = {
    "RavenscourtPark",
    "SouthParkFulham",
    "HurlinghamPark",
    "LytteltonPlayingFields",
    "BrockwellPark",
    "TelegraphHill",
}


def booking_url_for_slug(slug: str) -> str:
    """Customer-facing link for a venue's availability."""
    if slug in _LOGIN_GATED_BOOKING_PAGE_SLUGS:
        return f"{CLUBSPARK_ORGANISATION_WEBSITE}/{slug}"
    return f"{CLUBSPARK_ORGANISATION_WEBSITE}/{slug}/Booking/BookByDate"


class ClubSparkRequestStrategy(AbstractRequestStrategy):
    """Stub -- the crawler overrides ScraperCoroutines and issues one request per
    venue covering the whole requested date range (GetVenueSessions takes a
    startDate/endDate window, not a single date), the same kind of deviation
    Matchi/CitySport already make for their own API shapes. This strategy only
    supplies the base URL + metadata; the date-range query params are attached
    by the crawler itself."""

    category = "Tennis"

    @override
    def generate_request_details(
        self, sports_venue: SportsVenue, fetch_date: date, token: Optional[str] = None
    ) -> List[RequestDetailsWithMetadata]:
        return [
            RequestDetailsWithMetadata(
                url=(
                    f"{CLUBSPARK_ORGANISATION_WEBSITE}/v0/VenueBooking/"
                    f"{sports_venue.slug}/GetVenueSessions"
                ),
                headers=HEADERS,
                metadata=AdditionalRequestMetadata(
                    category=self.category,
                    date=fetch_date,
                    booking_url=booking_url_for_slug(sports_venue.slug),
                    sportsCentre=sports_venue,
                ),
            )
        ]


class ClubSparkTennisRequestStrategy(ClubSparkRequestStrategy):
    category = "Tennis"


class ClubSparkPadelRequestStrategy(ClubSparkRequestStrategy):
    category = "Padel"


class ClubSparkResponseParserStrategy(AbstractResponseParserStrategy):
    category = "Tennis"
    padel_only = False
    infer_indoor = False

    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        try:
            parsed = ClubSparkVenueSessionsResponse(**raw_response.content)
        except Exception as e:
            logging.error(f"ClubSpark: failed to parse GetVenueSessions response: {e}")
            return []

        metadata = raw_response.requestMetadata.metadata
        # GetVenueSessions returns one session block per court/resource. Emitting
        # one row per resource and letting the uid upsert dedupe would collapse
        # every multi-court slot to spaces=1. Aggregate by time/indoor instead,
        # so spaces is the number of bookable courts at that time.
        groups: Dict[tuple, dict] = defaultdict(
            lambda: {"resources": set(), "prices": []}
        )
        for resource in parsed.Resources:
            if self.padel_only:
                if not is_padel_resource(resource.Name, resource.Category):
                    continue
            elif not is_tennis_resource(resource.Name, resource.Category):
                continue
            indoor = resource.Location in (1, 2) if self.infer_indoor else False
            for day in resource.Days:
                try:
                    slot_date = datetime.fromisoformat(day.Date).date()
                except ValueError:
                    continue
                for session in day.Sessions:
                    # Category 1000 is an existing booking, not availability.
                    if session.Category != AVAILABLE_CATEGORY:
                        continue

                    # Some Category 0 sessions are reserved for staff/roles
                    # (e.g. Padel NTC 08:00-09:00 is "Administrator, NTC Front
                    # of House" and renders behind a padlock on the booking
                    # page). They are not public availability, even at £0.00.
                    if (session.Restrictions or "").strip():
                        continue

                    # An available session is a continuous window (e.g. Court 1
                    # free 06:00-14:30) rather than one bookable slot. Split it
                    # at the venue's MinimumInterval, which is the granularity
                    # the public booking page actually uses (Old Deer Park:
                    # 30-minute intervals at £5.70 each). Falling back to the
                    # session's Interval is only a safety net.
                    interval = (
                        parsed.MinimumInterval
                        or session.Interval
                        or (session.EndTime - session.StartTime)
                    )
                    if interval <= 0:
                        continue
                    slot_start = session.StartTime
                    while slot_start + interval <= session.EndTime:
                        starting_time = _minutes_to_time(slot_start)
                        ending_time = _minutes_to_time(slot_start + interval)
                        key = (slot_date, starting_time, ending_time, indoor)
                        groups[key]["resources"].add(
                            resource.ID or resource.Name
                        )
                        price = (
                            session.CourtCost
                            if session.CourtCost is not None
                            else session.CostFrom
                        )
                        if price is not None:
                            groups[key]["prices"].append(float(price))
                        slot_start += interval

        results: List[UnifiedParserSchema] = []
        for (slot_date, starting_time, ending_time, indoor), group in sorted(
            groups.items()
        ):
            prices = group["prices"]
            price = f"£{min(prices):.2f}" if prices else "N/A"
            results.append(
                UnifiedParserSchema(
                    category=self.category,
                    starting_time=starting_time,
                    ending_time=ending_time,
                    date=slot_date,
                    price=price,
                    spaces=len(group["resources"]),
                    composite_key=metadata.sportsCentre.composite_key,
                    last_refreshed=metadata.last_refreshed,
                    booking_url=metadata.booking_url,
                    indoor=indoor,
                )
            )
        return results


class ClubSparkTennisResponseParserStrategy(ClubSparkResponseParserStrategy):
    category = "Tennis"


class ClubSparkPadelResponseParserStrategy(ClubSparkResponseParserStrategy):
    category = "Padel"
    padel_only = True
    infer_indoor = True
