"""
Places Leisure strategy implementation.

Places Leisure runs on the same Gladstone booking engine as Better/GLL and
Tower Hamlets (see docs/clubs/tower-hamlets.md), but doesn't expose it
directly - calling placesleisure.gladstonego.cloud's API anonymously gets a
401. Instead, placesleisure.org (Umbraco CMS) proxies a public, anonymous
subset of it through its own API, used by this site's own timetable widget.

Two-phase fetch, unlike every other provider in this codebase:

1. GET https://www.placesleisure.org/centres/{slug}/ - the centre page embeds
   several weeks of schedule *structure* (which slots exist, when) as
   HTML-entity-escaped JSON directly in the page source. Look for
   `"ag":"BADMINTON"` / `"ag":"PICKLEBALL"` session objects. This is schedule
   only - it does NOT carry live availability.
2. GET /umbraco/api/timetables/getavailability?activityId=...&siteId=...&locationId=...&startDate=...
   once per unique (activityId, locationId, startDate) triple discovered in
   step 1, to get real per-court availability ("Available"/"Unavailable" per
   court). No auth needed for either step - confirmed live, no WAF block.

This means one HTML fetch per venue (cheap) followed by potentially hundreds
of availability calls per venue (one per timetabled slot across several
weeks) - comparable in request volume to Better/GLL. Confirmed live that this endpoint has no day/date-range bulk mode (see the
comment in `_fetch_and_build`), so that fan-out is structural, not a
self-imposed inefficiency - it's throttled via a strict shared rate limiter
instead (see `_paced_get`).

Time zone: schedule and availability timestamps are UTC ISO-8601. Converted
to Europe/London for display, same convention as every other provider.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import re
import time
from datetime import date, datetime
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx

import sportscanner.storage.postgres.tables
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.logger import logging

PLACES_LEISURE_ORGANISATION_WEBSITE = "https://www.placesleisure.org"

_LONDON_TZ = ZoneInfo("Europe/London")

# The Umbraco availability API rate-limits aggressively (HTTP 429): the
# 2026-08-23 GitHub Actions runs drowned in 429s when all 8 venues' availability
# requests shared the pipeline-wide 20-slot semaphore. A first attempt at a
# provider-local limiter (3 concurrent + a 0.3s sleep before each task's own
# request) still 429'd on 2026-08-30 - 3 workers independently pacing
# themselves at 0.3s yields ~6-10 req/s in bursts, not the ~3 req/s the
# spacing constant implies. Replaced with a real shared pacer below: every
# availability request funnels through one lock and waits out a hard minimum
# interval since the *previous* request fired, regardless of how many tasks
# are scheduled concurrently - an actual guaranteed rate ceiling rather than
# an approximate one.
# Empirically tuned live against Latchmere Leisure Centre (2026-08-30): at
# 0.5s this 429'd on every single first attempt (100%), recovering only via
# the retry below. At 1.5s, 52/52 slots came back clean with just 3 transient
# 429s total (~6%), all recovered on the first retry - no exhausted-retry
# failures. Push this higher only if live logs show a sustained 429 rate
# again; pushing it lower reintroduces the 100%-retry pattern.
_MIN_REQUEST_INTERVAL_SECONDS = 1.5  # hard ceiling: ~0.67 req/s
_rate_limiter_lock = asyncio.Lock()
_last_request_at: float = 0.0

# 429 is a transient "slow down", not a real failure - retrying (honoring
# Retry-After when the server sends one) recovers the slot instead of
# permanently dropping it from this run.
_MAX_429_RETRIES = 3
_BACKOFF_SECONDS = (1.0, 2.0, 4.0)


async def _paced_get(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """GET `url`, first waiting out the shared minimum inter-request interval,
    then retrying with backoff on 429 (honoring Retry-After if present)."""
    global _last_request_at
    for attempt in range(_MAX_429_RETRIES + 1):
        async with _rate_limiter_lock:
            wait = _MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_request_at = time.monotonic()
            resp = await client.get(url, **kwargs)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp
        if attempt == _MAX_429_RETRIES:
            resp.raise_for_status()  # exhausted retries - raise so the caller logs/drops as before
        retry_after = resp.headers.get("Retry-After")
        delay = float(retry_after) if retry_after and retry_after.isdigit() else _BACKOFF_SECONDS[attempt]
        logging.warning(f"Places Leisure: 429 on {url}, retrying in {delay}s (attempt {attempt + 1})")
        await asyncio.sleep(delay)
    raise AssertionError("unreachable")  # loop always returns or raises above


_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
}

# (start_iso, end_iso, activityId, locationId)
_SessionTuple = Tuple[str, str, str, str]


def _to_london(iso_ts: str) -> datetime:
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).astimezone(_LONDON_TZ)


class PlacesLeisureSlotFetcher:
    """One instance per sport - `activity_group` is the schedule's `ag` value
    ("BADMINTON" or "PICKLEBALL"), `category` is what UnifiedParserSchema
    expects (matches the rest of the codebase's Title Case convention)."""

    def __init__(self, activity_group: str, category: str):
        self.activity_group = activity_group
        self.category = category
        self._session_pattern = re.compile(
            r'\{"s":"([^"]+)","e":"([^"]+)","aId":"([^"]+)","t":[^,]*,"et":[^,]*,'
            r'"al":"([^"]+)","lc":"[^"]*","ag":"' + re.escape(activity_group) + r'"'
        )

    async def crawl_venue(
        self,
        client: httpx.AsyncClient,
        venue: sportscanner.storage.postgres.tables.SportsVenue,
        site_id: str,
        search_dates: List[date],
        semaphore: asyncio.Semaphore,
    ) -> List[UnifiedParserSchema]:
        sessions = await self._fetch_schedule(client, venue.slug, semaphore)
        allowed_dates = set(search_dates)
        relevant = [s for s in sessions if _to_london(s[0]).date() in allowed_dates]
        if not relevant:
            logging.debug(
                f"Places Leisure {venue.venue_name}: no {self.category} sessions "
                f"in the requested date window"
            )
            return []

        tasks = [
            self._fetch_and_build(client, venue, site_id, session)
            for session in relevant
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        slots: List[UnifiedParserSchema] = []
        for r in results:
            if isinstance(r, Exception):
                logging.error(f"Places Leisure {venue.venue_name} task raised: {r}")
            elif r:
                slots.append(r)
        return slots

    async def _fetch_schedule(
        self, client: httpx.AsyncClient, slug: str, semaphore: asyncio.Semaphore
    ) -> List[_SessionTuple]:
        url = f"{PLACES_LEISURE_ORGANISATION_WEBSITE}/centres/{slug}/"
        try:
            async with semaphore:
                resp = await client.get(url, headers=_HEADERS, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            logging.error(
                f"Places Leisure: failed to fetch centre page for {slug}: {exc}"
            )
            return []

        content = html_lib.unescape(resp.text)
        matches = self._session_pattern.findall(content)

        # The same (start, activityId, locationId) can appear more than once in
        # the embedded schedule (once per bookable resource sharing the slot
        # group) - dedupe before firing one availability request each.
        seen = set()
        uniq: List[_SessionTuple] = []
        for s, e, activity_id, location_id in matches:
            key = (s, activity_id, location_id)
            if key not in seen:
                seen.add(key)
                uniq.append((s, e, activity_id, location_id))
        return uniq

    async def _fetch_and_build(
        self,
        client: httpx.AsyncClient,
        venue: sportscanner.storage.postgres.tables.SportsVenue,
        site_id: str,
        session: _SessionTuple,
    ) -> Optional[UnifiedParserSchema]:
        # One call per distinct scheduled StartDateTime is not a self-imposed
        # inefficiency - confirmed live against this exact endpoint that it has
        # no day/date-range bulk mode: a date-only or off-grid `startDate`
        # returns {"success":false,"errors":["Failed to get availability"]},
        # and an added `endDate` param is silently ignored. It already returns
        # every court for that one timestamp in a single response (see `courts`
        # below) - the fan-out is genuinely per-timeslot, not per-court.
        start_iso, end_iso, activity_id, location_id = session
        params = {
            "activityId": activity_id,
            "siteId": site_id,
            "locationId": location_id,
            "startDate": start_iso,
        }
        try:
            resp = await _paced_get(
                client,
                f"{PLACES_LEISURE_ORGANISATION_WEBSITE}/umbraco/api/timetables/getavailability",
                params=params,
                headers={
                    **_HEADERS,
                    "Referer": f"{PLACES_LEISURE_ORGANISATION_WEBSITE}/centres/{venue.slug}/",
                },
                timeout=30,
            )
            payload = resp.json()
        except Exception as exc:
            logging.error(
                f"Places Leisure {venue.venue_name} availability fetch failed "
                f"for {start_iso}: {exc}"
            )
            return None

        courts = payload.get("data", [])
        if not courts:
            return None
        available = sum(1 for c in courts if c.get("status") == "Available")

        start_local = _to_london(start_iso)
        end_local = _to_london(end_iso)

        return UnifiedParserSchema(
            category=self.category,
            starting_time=start_local.time(),
            ending_time=end_local.time(),
            date=start_local.date(),
            # No pay-as-you-go price is exposed anonymously anywhere in this
            # flow - not on the centre page (only monthly membership prices
            # are shown), not in the availability response, and the booking
            # deep-link requires a session to render. Hardcoded to a London
            # leisure-centre-average peak badminton rate until a real pricing
            # source is found (comparable Better/GLL centres charge £14-£16
            # for peak evening slots) - revisit if Places Leisure exposes
            # per-centre pricing anonymously in the future.
            price="£12.00",
            spaces=available,
            composite_key=venue.composite_key,
            last_refreshed=datetime.now(),
            booking_url=f"{PLACES_LEISURE_ORGANISATION_WEBSITE}/centres/{venue.slug}/",
        )
