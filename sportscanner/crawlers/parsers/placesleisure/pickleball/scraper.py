from datetime import date
from typing import Any, Coroutine, List

import asyncio

from sportscanner.crawlers.anonymize.proxies import httpxAsyncClient
from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.core.interfaces import AbstractRequestStrategy, AbstractResponseParserStrategy, BaseCrawler
from sportscanner.crawlers.parsers.core.schemas import RequestDetailsWithMetadata, RawResponseData, UnifiedParserSchema
from sportscanner.crawlers.parsers.placesleisure.core.strategy import (
    PLACES_LEISURE_ORGANISATION_WEBSITE,
    PlacesLeisureSlotFetcher,
)
from sportscanner.crawlers.parsers.placesleisure.core.venues import SLUG_TO_SITE_ID
from sportscanner.logger import logging
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.variables import settings


class _StubRequestStrategy(AbstractRequestStrategy):
    """See badminton/scraper.py's equivalent stub - Places Leisure bypasses
    the standard per-venue request loop entirely (core/strategy.py has the
    full two-phase fetch design)."""

    @override
    def generate_request_details(self, sports_venue, fetch_date, token=None) -> List[RequestDetailsWithMetadata]:
        return []


class _StubResponseParserStrategy(AbstractResponseParserStrategy):
    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        return []


class PlacesLeisurePickleballCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(
            request_strategy=_StubRequestStrategy(),
            response_parser_strategy=_StubResponseParserStrategy(),
            organisation_website=PLACES_LEISURE_ORGANISATION_WEBSITE,
        )
        self._fetcher = PlacesLeisureSlotFetcher(activity_group="PICKLEBALL", category="Pickleball")

    @override
    def ScraperCoroutines(
            self, sports_venues: List[SportsVenue], dates: List[date]
    ) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
        return self._crawl_async(sports_venues, dates)

    async def _crawl_async(
            self, sports_venues: List[SportsVenue], dates: List[date]
    ) -> List[UnifiedParserSchema]:
        matched = [(v, SLUG_TO_SITE_ID[v.slug]) for v in sports_venues if v.slug in SLUG_TO_SITE_ID]
        unmatched = [v.slug for v in sports_venues if v.slug not in SLUG_TO_SITE_ID]
        if unmatched:
            logging.warning(
                f"Places Leisure: {len(unmatched)} venue(s) have no siteId in "
                f"SLUG_TO_SITE_ID - add them to core/venues.py: {unmatched}"
            )
        if not matched:
            return []

        logging.info(f"Places Leisure: crawling {len(matched)} venue(s) for pickleball")
        semaphore = asyncio.Semaphore(settings.CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER)
        async with httpxAsyncClient() as client:
            tasks = [
                self._fetcher.crawl_venue(client, venue, site_id, dates, semaphore)
                for venue, site_id in matched
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_slots: List[UnifiedParserSchema] = []
        for r in results:
            if isinstance(r, Exception):
                logging.error(f"Places Leisure venue task raised: {r}")
            elif r:
                all_slots.extend(r)
        return all_slots


def coroutines(search_dates: List[date]) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
    """Entry point for pipeline.py - returns a coroutine suitable for SportscannerCrawlerBot."""
    crawler = PlacesLeisurePickleballCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="pickleball")
    if not venues:
        logging.warning("Places Leisure: no pickleball venues found in DB - skipping")

        async def _empty():
            return []

        return _empty()
    return crawler.ScraperCoroutines(venues, search_dates)


if __name__ == "__main__":
    from datetime import timedelta
    from rich import print

    _dates = [date.today() + timedelta(days=i) for i in range(7)]
    print(f"Places Leisure pickleball test run for dates: {_dates}")
    crawler = PlacesLeisurePickleballCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="pickleball")
    if not venues:
        print("[yellow]No Places Leisure pickleball venues in DB. Add entries to venues.json first.[/yellow]")
    else:
        results = asyncio.run(crawler._crawl_async(venues, _dates))
        print(f"Results ({len(results)} slots):")
        for r in results[:10]:
            print(r)
