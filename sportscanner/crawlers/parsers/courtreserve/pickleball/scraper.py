"""
CourtReserve Pickleball scraper (Lemon Pickleball, CourtReserve orgId 13469).

Bypasses BaseCrawler's per-(venue, date) loop with the established
ScraperCoroutines override pattern (see playtomic/): a single anonymous POST to
/Online/Calendar/ReadCalendarEvents/13469 returns every session occurrence for
a date across all venues, so fetching per venue would just multiply identical
requests. Availability is genuinely public here - it is the portal's Session
Calendar tab that an anonymous browser renders. Court reservations and the
events listing API are login-gated; only this calendar read is open.

Venue resolution: session titles embed the venue ("Social Play - Hampstead"),
matched longest-first against VENUE_KEY_TO_SLUG in core/strategy.py and then
against the slug of each DB venue row for this organisation. Adding a new
Lemon venue = add it to venues.json with a slug from VENUE_KEY_TO_SLUG.

Usage (pipeline):
    coroutines(search_dates)  ->  coroutine yielding List[UnifiedParserSchema]

Direct run:
    python -m sportscanner.crawlers.parsers.courtreserve.pickleball.scraper
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Coroutine, Dict, List

import httpx

from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.crawlers.anonymize.proxies import httpxAsyncClient
from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.core.interfaces import BaseCrawler
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.courtreserve.core.strategy import (
    COURTRESERVE_CALENDAR_READ_URL,
    COURTRESERVE_ORGANISATION_WEBSITE,
    build_calendar_read_payload,
    parse_calendar_events,
)
from sportscanner.logger import logging
from sportscanner.utils import async_timer
from sportscanner.variables import settings
from rich import print


class CourtReservePickleballCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(
            request_strategy=None,
            response_parser_strategy=None,
            organisation_website=COURTRESERVE_ORGANISATION_WEBSITE,
        )

    @async_timer
    async def _crawl_async(
        self,
        sports_venues: List[SportsVenue],
        dates: List[date],
    ) -> List[UnifiedParserSchema]:
        logging.info(
            f"CourtReserve: crawling {len(dates)} dates against "
            f"{len(sports_venues)} registered pickleball venues"
        )
        slug_to_venue: Dict[str, SportsVenue] = {
            venue.slug: venue for venue in sports_venues
        }
        # The calendar read is org-wide: one request covers every venue for a
        # date, so the request count is len(dates), not venues x dates. Still
        # capped - this bypasses BaseCrawler's semaphore-bounded loop.
        semaphore = asyncio.Semaphore(
            settings.CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER
        )

        async def fetch_date(client: httpx.AsyncClient, fetch_date: date):
            async with semaphore:
                response = await client.post(
                    COURTRESERVE_CALENDAR_READ_URL,
                    data=build_calendar_read_payload(fetch_date),
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
                response.raise_for_status()
                return response.json().get("Data", [])

        async with httpxAsyncClient() as client:
            results = await asyncio.gather(
                *(fetch_date(client, d) for d in dates), return_exceptions=True
            )

        all_slots: List[UnifiedParserSchema] = []
        rows_parsed = 0
        for fetch_date, result in zip(dates, results):
            if isinstance(result, Exception):
                logging.error(
                    f"CourtReserve: calendar read failed for {fetch_date}: {result}"
                )
                continue
            slots = parse_calendar_events(result, slug_to_venue, category="Pickleball")
            rows_parsed += len(result)
            all_slots.extend(slots)

        logging.info(
            f"CourtReserve: {rows_parsed} calendar rows -> {len(all_slots)} "
            f"slots across {len(slug_to_venue)} venues"
        )
        return all_slots

    @override
    def ScraperCoroutines(
        self,
        sports_venues: List[SportsVenue],
        dates: List[date],
    ) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
        return self._crawl_async(sports_venues, dates)


def coroutines(
    search_dates: List[date],
) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
    """Entry point for pipeline.py — returns a coroutine suitable for SportscannerCrawlerBot."""
    crawler = CourtReservePickleballCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="pickleball")
    if not venues:
        logging.warning("CourtReserve: no pickleball venues found in DB — skipping")

        async def _empty():
            return []

        return _empty()
    return crawler.ScraperCoroutines(venues, search_dates)


if __name__ == "__main__":
    _dates = [date.today() + timedelta(days=i) for i in range(3)]
    print(f"CourtReserve pickleball test run for dates: {_dates}")
    crawler = CourtReservePickleballCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="pickleball")
    if not venues:
        print(
            "[yellow]No pickleball venues in DB.  Add entries to venues.json first.[/yellow]"
        )
    else:
        results = asyncio.run(crawler._crawl_async(venues, _dates))
        available = [r for r in results if r.spaces > 0]
        print(f"Results ({len(results)} slots, {len(available)} with spaces > 0):")
        for r in results[:20]:
            print(r)
