"""
Matchi Padel scraper.

Matchi's /book/findFacilities endpoint returns ALL London padel venues in one
(paginated) HTML response, so we override ScraperCoroutines to iterate over
dates instead of the usual (venue × date) product.  The venue list queried from
the DB is used solely to build a slug → SportsVenue lookup; only slots whose
facility slug matches a DB entry are emitted.

Usage (pipeline):
    coroutines(search_dates)  →  coroutine yielding List[UnifiedParserSchema]

Direct run:
    python -m sportscanner.crawlers.parsers.matchi.padel.scraper
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Coroutine, Dict, List, Any

import sportscanner.storage.postgres.tables
from sportscanner.crawlers.anonymize.proxies import httpxAsyncClient
from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.core.interfaces import BaseCrawler
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.matchi.core.strategy import (
    MatchiRequestStrategy,
    MatchiResponseParserStrategy,
    MatchiSlotFetcher,
    MATCHI_ORGANISATION_WEBSITE,
)
from sportscanner.logger import logging
from sportscanner.utils import async_timer
from rich import print


class MatchiPadelCrawler(BaseCrawler):
    def __init__(self):
        self._fetcher = MatchiSlotFetcher()
        super().__init__(
            request_strategy=MatchiRequestStrategy(),
            response_parser_strategy=MatchiResponseParserStrategy(),
            organisation_website=MATCHI_ORGANISATION_WEBSITE,
        )

    @async_timer
    async def _crawl_async(
        self,
        sports_venues: List[sportscanner.storage.postgres.tables.SportsVenue],
        dates: List[date],
    ) -> List[UnifiedParserSchema]:
        venue_by_slug: Dict[str, sportscanner.storage.postgres.tables.SportsVenue] = {
            v.slug: v for v in sports_venues
        }
        logging.info(
            f"Matchi: crawling {len(dates)} dates against "
            f"{len(venue_by_slug)} registered padel venues"
        )
        async with httpxAsyncClient() as client:
            tasks = [
                self._fetcher.crawl_date(client, d, venue_by_slug)
                for d in dates
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_slots: List[UnifiedParserSchema] = []
        for r in results:
            if isinstance(r, Exception):
                logging.error(f"Matchi date task raised an exception: {r}")
            elif r:
                all_slots.extend(r)
        return all_slots

    @override
    def ScraperCoroutines(
        self,
        sports_venues: List[sportscanner.storage.postgres.tables.SportsVenue],
        dates: List[date],
    ) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
        return self._crawl_async(sports_venues, dates)


def coroutines(search_dates: List[date]) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
    """Entry point for pipeline.py — returns a coroutine suitable for SportscannerCrawlerBot."""
    crawler = MatchiPadelCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="padel")
    if not venues:
        logging.warning("Matchi: no padel venues found in DB — skipping")

        async def _empty():
            return []

        return _empty()
    return crawler.ScraperCoroutines(venues, search_dates)


if __name__ == "__main__":
    _dates = [date.today() + timedelta(days=i) for i in range(3)]
    print(f"Matchi padel test run for dates: {_dates}")
    crawler = MatchiPadelCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="padel")
    if not venues:
        print("[yellow]No padel venues in DB.  Add entries to venues.json first.[/yellow]")
    else:
        results = asyncio.run(crawler._crawl_async(venues, _dates))
        print(f"Results ({len(results)} slots):")
        for r in results:
            print(r)
