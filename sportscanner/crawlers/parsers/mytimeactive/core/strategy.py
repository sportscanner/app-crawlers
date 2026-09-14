import os
from collections import defaultdict
from datetime import date, datetime, timedelta, time
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from curl_cffi.requests import Session as CurlSession
from pydantic import ValidationError

from sportscanner.crawlers.anonymize.flaresolverr import get_cookie_via_flaresolverr
from sportscanner.crawlers.anonymize.proxies import next_impersonate_profile
from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.core.interfaces import (
    AbstractRequestStrategy,
    AbstractResponseParserStrategy,
    BaseCrawler,
)
from sportscanner.crawlers.parsers.core.schemas import (
    AdditionalRequestMetadata,
    RawResponseData,
    RequestDetailsWithMetadata,
    UnifiedParserSchema,
)
from sportscanner.crawlers.parsers.mytimeactive.core.schema import (
    GladstoneGoSessionSchema,
)
from sportscanner.logger import logging
from sportscanner.storage.postgres.tables import SportsVenue

GLADSTONEGO_PORTAL_BASE = "https://mytimeactive.gladstonego.cloud"
ORGANISATION_WEBSITE = "https://www.mytimeactive.co.uk"

# Activity IDs on Gladstone Go discovered via /api/configuration/activity-groups.
# The Spa at Beckenham offers badminton. Walnuts Leisure Centre offers badminton and squash.
# Pavilion (Bromley) and West Wickham Leisure Centre do not have badminton or squash courts.
BADMINTON_ACTIVITY_IDS: Dict[str, str] = {
    "SPA": "SPAACT0016",
    "WAL": "WALACT0008",
}

SQUASH_ACTIVITY_IDS: Dict[str, str] = {
    "WAL": "WALACT0009",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

_LONDON = ZoneInfo("Europe/London")


_JWT_FETCH_ATTEMPTS = 4


def get_anonymous_jwt() -> Optional[str]:
    """Fetches an anonymous session JWT from Gladstone Go samlauthentication endpoint.

    Uses curl_cffi with a browser TLS fingerprint: the endpoint 403s plain
    httpx/ssl handshakes from datacenter IPs such as GitHub Actions runners
    (confirmed in the 2026-08-23 badminton/squash workflow logs, 0/12 and 0/6
    requests returned data) while succeeding locally from residential IPs.
    Same WAF class as CitySport, same fix.

    Every run was still getting 403 on every attempt (see 2026-09-14 badminton
    logs, 0/13 succeeded) despite this - a single fixed impersonation profile
    isn't enough here, so this retries across `next_impersonate_profile()`'s
    rotation before giving up, same rationale as
    `anonymize/proxies.get_with_proxy_fallback_on_403`.

    Confirmed live (2026-09) that rotation alone still doesn't get past this
    one: real Chrome traffic itself is required, not just a matching TLS
    fingerprint - a genuine headless browser (FlareSolverr) gets a clean 200
    with no challenge shown at all ("Challenge not detected!"), meaning
    Cloudflare here is scoring JS-execution capability rather than (or in
    addition to) the handshake. So FlareSolverr is tried as a final fallback,
    extracting the `Jwt` cookie straight from its solved browser session. A
    true no-op unless `FLARESOLVERR_URL` is set.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, _JWT_FETCH_ATTEMPTS + 1):
        profile = next_impersonate_profile()
        try:
            with CurlSession(
                headers={
                    "user-agent": USER_AGENT,
                    "accept": "application/json",
                    "x-use-sso": "1",
                },
                impersonate=profile,
                timeout=15.0,
            ) as session:
                res = session.get(
                    f"{GLADSTONEGO_PORTAL_BASE}/api/samlauthentication/anonymous"
                )
                res.raise_for_status()
                jwt = session.cookies.get("Jwt")
                if jwt:
                    return jwt
                logging.error(
                    "No Jwt cookie returned by Gladstone Go anonymous auth endpoint "
                    f"(attempt {attempt}/{_JWT_FETCH_ATTEMPTS}, profile {profile})"
                )
        except Exception as e:
            last_exc = e
            logging.debug(
                f"Failed to fetch anonymous JWT from {GLADSTONEGO_PORTAL_BASE} "
                f"(attempt {attempt}/{_JWT_FETCH_ATTEMPTS}, profile {profile}): {e}"
            )

    jwt = get_cookie_via_flaresolverr(
        f"{GLADSTONEGO_PORTAL_BASE}/api/samlauthentication/anonymous",
        cookie_name="Jwt",
        log_label="mytimeactive",
    )
    if jwt:
        return jwt

    logging.error(
        f"Failed to fetch anonymous JWT from {GLADSTONEGO_PORTAL_BASE} after "
        f"{_JWT_FETCH_ATTEMPTS} attempts across rotated TLS profiles"
        f"{' + FlareSolverr' if os.environ.get('FLARESOLVERR_URL') else ''}: {last_exc}"
    )
    return None


def _round_slot_time(dt_val: datetime) -> time:
    """Converts UTC datetime from Gladstone Go to Europe/London local time,
    rounding up 59-second timestamps to the full minute."""
    if dt_val.tzinfo is None:
        dt_val = dt_val.replace(tzinfo=ZoneInfo("UTC"))
    local_dt = dt_val.astimezone(_LONDON)
    if local_dt.second > 0:
        local_dt = (local_dt + timedelta(minutes=1)).replace(second=0, microsecond=0)
    return local_dt.time()


class MytimeActiveRequestStrategy(AbstractRequestStrategy):
    """Generates request details for Gladstone Go availability API."""

    def __init__(self, category: str, activity_ids: Dict[str, str]):
        self.category = category
        self.activity_ids = activity_ids

    @override
    def generate_request_details(
        self, sports_venue: SportsVenue, fetch_date: date, token: Optional[str] = None
    ) -> List[RequestDetailsWithMetadata]:
        activity_id = self.activity_ids.get(sports_venue.slug)
        if not activity_id:
            return []

        url = (
            f"{GLADSTONEGO_PORTAL_BASE}/api/availability/V2/sessions"
            f"?siteIds={sports_venue.slug}"
            f"&activityIDs={activity_id}"
            f"&webBookableOnly=false"
            f"&dateFrom={fetch_date.isoformat()}"
        )
        headers = {
            "accept": "application/json",
            "user-agent": USER_AGENT,
            "x-use-sso": "1",
        }
        if token:
            headers["Cookie"] = f"Jwt={token}"

        booking_url = f"{GLADSTONEGO_PORTAL_BASE}/book/calendar/{activity_id}?activityDate={fetch_date.isoformat()}"
        return [
            RequestDetailsWithMetadata(
                url=url,
                headers=headers,
                payload={},
                token=token,
                cookies=None,
                metadata=AdditionalRequestMetadata(
                    category=self.category,
                    date=fetch_date,
                    price="",
                    booking_url=booking_url,
                    sportsCentre=sports_venue,
                ),
            )
        ]


class GladstoneGoResponseParserStrategy(AbstractResponseParserStrategy):
    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        metadata = raw_response.requestMetadata.metadata
        try:
            sessions = [
                GladstoneGoSessionSchema(**session_block)
                for session_block in raw_response.content
            ]
        except ValidationError as e:
            logging.error(
                f"Unable to apply GladstoneGoSessionSchema to raw API json:\n{e}"
            )
            return []

        # Filter down to sessions for this specific date and venue. webBookable
        # is checked here (rather than via webBookableOnly=true on the request)
        # because the request intentionally fetches in-centre-only sessions too;
        # non-web-bookable sessions must still be dropped or their booking_url
        # deep link 404s into Gladstone Go's "no timetable slots" error page
        # (confirmed for The Walnuts Leisure Centre, which is phone/walk-in only
        # for badminton and squash as of 2026-08-26).
        target_date_str = metadata.date.isoformat()
        day_sessions = [
            s
            for s in sessions
            if s.date == target_date_str
            and s.siteId == metadata.sportsCentre.slug
            and s.webBookable
        ]

        # Aggregate availability across courts for each unique (start_time, end_time) slot
        slots_map: Dict[tuple[time, time], int] = defaultdict(int)
        for session in day_sessions:
            for location in session.locations:
                for slot in location.slots:
                    st = _round_slot_time(slot.startTime)
                    et = _round_slot_time(slot.endTime)
                    spaces = (
                        slot.availability.inCentre
                        if (
                            slot.status == "Available" or slot.availability.inCentre > 0
                        )
                        else 0
                    )
                    slots_map[(st, et)] += spaces

        unified_schema_output: List[UnifiedParserSchema] = []
        for (st, et), spaces in sorted(slots_map.items()):
            unified_schema_output.append(
                UnifiedParserSchema(
                    category=metadata.category,
                    starting_time=st,
                    ending_time=et,
                    date=metadata.date,
                    price=metadata.price or "",
                    spaces=spaces,
                    composite_key=metadata.sportsCentre.composite_key,
                    last_refreshed=metadata.last_refreshed,
                    booking_url=metadata.booking_url,
                )
            )
        return unified_schema_output


class MytimeActiveCrawler(BaseCrawler):
    """Base crawler for Mytime Active venues managing the anonymous session JWT."""

    def __init__(
        self,
        request_strategy: AbstractRequestStrategy,
        response_parser_strategy: AbstractResponseParserStrategy,
        organisation_website: str = ORGANISATION_WEBSITE,
    ):
        super().__init__(
            request_strategy=request_strategy,
            response_parser_strategy=response_parser_strategy,
            organisation_website=organisation_website,
        )
        self._token: Optional[str] = get_anonymous_jwt()

    @override
    def _auth_token(self) -> Optional[str]:
        if not self._token:
            self._token = get_anonymous_jwt()
        return self._token
