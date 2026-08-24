"""
ClubSpark (LTA) strategy implementations.

GetVenueSessions is an unauthenticated public JSON endpoint (confirmed live,
no auth headers/cookies required) that returns every court's session grid for
a venue across a startDate/endDate range in one call:

    GET https://clubspark.lta.org.uk/v0/VenueBooking/{VenueSlug}/GetVenueSessions
        ?resourceID=&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&roleId=

Each session has a `Category`: 1000 = genuinely bookable, 8000 = closed,
2000 = occupied by a coaching/programmed session. Only 1000 rows are real
availability. Venue slugs must be verified via the companion `GetSettings`
endpoint before use — guessed slugs (e.g. from a park's common name) 404
silently rather than falling back to anything useful.
"""

from datetime import date, datetime, timedelta
from typing import Any, Coroutine, List, Optional

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
BOOKABLE_CATEGORY = 1000

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


class ClubSparkTennisRequestStrategy(AbstractRequestStrategy):
    """Stub — ClubSparkTennisCrawler overrides ScraperCoroutines and issues one
    request per venue covering the whole requested date range (GetVenueSessions
    takes a startDate/endDate window, not a single date), the same kind of
    deviation Matchi/CitySport already make for their own API shapes. This
    strategy only supplies the base URL + metadata; the date-range query
    params are attached by the crawler itself."""

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
                    category="Tennis",
                    date=fetch_date,
                    booking_url=booking_url_for_slug(sports_venue.slug),
                    sportsCentre=sports_venue,
                ),
            )
        ]


class ClubSparkTennisResponseParserStrategy(AbstractResponseParserStrategy):
    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        try:
            parsed = ClubSparkVenueSessionsResponse(**raw_response.content)
        except Exception as e:
            logging.error(f"ClubSpark: failed to parse GetVenueSessions response: {e}")
            return []

        metadata = raw_response.requestMetadata.metadata
        results: List[UnifiedParserSchema] = []
        for resource in parsed.Resources:
            for day in resource.Days:
                try:
                    slot_date = datetime.fromisoformat(day.Date).date()
                except ValueError:
                    continue
                for session in day.Sessions:
                    if session.Category != BOOKABLE_CATEGORY:
                        continue
                    starting_time = (
                        datetime.min + timedelta(minutes=session.StartTime)
                    ).time()
                    ending_time = (
                        datetime.min + timedelta(minutes=session.EndTime)
                    ).time()
                    price = (
                        f"£{session.CourtCost:.2f}"
                        if session.CourtCost is not None
                        else "N/A"
                    )
                    results.append(
                        UnifiedParserSchema(
                            category="Tennis",
                            starting_time=starting_time,
                            ending_time=ending_time,
                            date=slot_date,
                            price=price,
                            spaces=1,
                            composite_key=metadata.sportsCentre.composite_key,
                            last_refreshed=metadata.last_refreshed,
                            booking_url=metadata.booking_url,
                        )
                    )
        return results
