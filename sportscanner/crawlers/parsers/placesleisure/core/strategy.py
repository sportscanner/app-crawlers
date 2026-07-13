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
weeks) - comparable in request volume to Better/GLL, and handled the same way
via a per-provider concurrency semaphore.

Time zone: schedule and availability timestamps are UTC ISO-8601. Converted
to Europe/London for display, same convention as every other provider.
"""
from __future__ import annotations

import asyncio
import html as html_lib
import re
from datetime import date, datetime
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx

import sportscanner.storage.postgres.tables
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.logger import logging

PLACES_LEISURE_ORGANISATION_WEBSITE = "https://www.placesleisure.org"

_LONDON_TZ = ZoneInfo("Europe/London")

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
            self._fetch_and_build(client, venue, site_id, session, semaphore)
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
            logging.error(f"Places Leisure: failed to fetch centre page for {slug}: {exc}")
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
        semaphore: asyncio.Semaphore,
    ) -> Optional[UnifiedParserSchema]:
        start_iso, end_iso, activity_id, location_id = session
        params = {
            "activityId": activity_id,
            "siteId": site_id,
            "locationId": location_id,
            "startDate": start_iso,
        }
        try:
            async with semaphore:
                resp = await client.get(
                    f"{PLACES_LEISURE_ORGANISATION_WEBSITE}/umbraco/api/timetables/getavailability",
                    params=params,
                    headers={
                        **_HEADERS,
                        "Referer": f"{PLACES_LEISURE_ORGANISATION_WEBSITE}/centres/{venue.slug}/",
                    },
                    timeout=30,
                )
            resp.raise_for_status()
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
            # deep-link requires a session to render. Left honest rather than
            # guessed; revisit if a pricing source is found.
            price="Check website",
            spaces=available,
            composite_key=venue.composite_key,
            last_refreshed=datetime.now(),
            booking_url=f"{PLACES_LEISURE_ORGANISATION_WEBSITE}/centres/{venue.slug}/",
        )
