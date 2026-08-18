"""
Playtomic Tennis scraper.

Identical API/response shape to Playtomic Padel (playtomic/padel/scraper.py) --
Playtomic's availability response carries no sport field, so sport is purely a
request parameter (`sport_id=TENNIS`, confirmed live against a real dual-sport
venue: distinct resource_ids and pricing from the same tenant's PADEL response).
Reuses the shared PlaytomicAvailabilityFetcher, just constructed with the
tennis sport_id/category instead of padel's.

Adding a new venue: add it to venues.json (organisation: Playtomic, slug =
tenant_uid, sports: ["tennis"]) and add the slug -> tenant_id entry to
SLUG_TO_TENANT_ID in core/strategy.py (shared with padel -- one map for both
sports since tenant_id identifies the club, not the sport).

Usage (pipeline):
    coroutines(search_dates)  ->  coroutine yielding List[UnifiedParserSchema]

Direct run:
    python -m sportscanner.crawlers.parsers.playtomic.tennis.scraper
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Coroutine, List

from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.crawlers.anonymize.proxies import httpxAsyncClient
from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.core.interfaces import BaseCrawler
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.playtomic.core.strategy import (
    PlaytomicTennisRequestStrategy,
    PlaytomicResponseParserStrategy,
    PlaytomicAvailabilityFetcher,
    PLAYTOMIC_ORGANISATION_WEBSITE,
    SLUG_TO_TENANT_ID,
    TENNIS_SPORT_ID,
)
from sportscanner.logger import logging
from sportscanner.utils import async_timer
from sportscanner.variables import settings
from rich import print


class PlaytomicTennisCrawler(BaseCrawler):
    def __init__(self):
        self._fetcher = PlaytomicAvailabilityFetcher(sport_id=TENNIS_SPORT_ID, category="Tennis")
        super().__init__(
            request_strategy=PlaytomicTennisRequestStrategy(),
            response_parser_strategy=PlaytomicResponseParserStrategy(),
            organisation_website=PLAYTOMIC_ORGANISATION_WEBSITE,
        )

    @async_timer
    async def _crawl_async(
        self,
        sports_venues: List[SportsVenue],
        dates: List[date],
    ) -> List[UnifiedParserSchema]:
        logging.info(
            f"Playtomic: crawling {len(dates)} dates against "
            f"{len(sports_venues)} registered tennis venues"
        )

        matched = [
            (venue, SLUG_TO_TENANT_ID[venue.slug])
            for venue in sports_venues
            if venue.slug in SLUG_TO_TENANT_ID
        ]
        unmatched = [v.slug for v in sports_venues if v.slug not in SLUG_TO_TENANT_ID]
        if unmatched:
            logging.warning(
                f"Playtomic: {len(unmatched)} venue(s) have no tenant_id in SLUG_TO_TENANT_ID "
                f"— add them to core/strategy.py: {unmatched}"
            )
        if not matched:
            logging.warning("Playtomic: no venues with known tenant_ids — aborting")
            return []

        logging.info(f"Playtomic: fetching tennis availability for {len(matched)} venues × {len(dates)} dates")
        semaphore = asyncio.Semaphore(settings.CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER)
        async with httpxAsyncClient() as client:
            tasks = [
                self._fetcher.fetch_venue_date(client, venue, tenant_id, d, semaphore)
                for venue, tenant_id in matched
                for d in dates
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_slots: List[UnifiedParserSchema] = []
        for r in results:
            if isinstance(r, Exception):
                logging.error(f"Playtomic tennis availability task raised: {r}")
            elif r:
                all_slots.extend(r)

        return all_slots

    @override
    def ScraperCoroutines(
        self,
        sports_venues: List[SportsVenue],
        dates: List[date],
    ) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
        return self._crawl_async(sports_venues, dates)


def coroutines(search_dates: List[date]) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
    """Entry point for pipeline.py — returns a coroutine suitable for SportscannerCrawlerBot."""
    crawler = PlaytomicTennisCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="tennis")
    if not venues:
        logging.warning("Playtomic: no tennis venues found in DB — skipping")

        async def _empty():
            return []

        return _empty()
    return crawler.ScraperCoroutines(venues, search_dates)


if __name__ == "__main__":
    _dates = [date.today() + timedelta(days=i) for i in range(3)]
    print(f"Playtomic tennis test run for dates: {_dates}")
    crawler = PlaytomicTennisCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="tennis")
    if not venues:
        print("[yellow]No tennis venues in DB.  Add entries to venues.json first.[/yellow]")
    else:
        results = asyncio.run(crawler._crawl_async(venues, _dates))
        print(f"Results ({len(results)} slots):")
        for r in results:
            print(r)
