"""
Matchi Tennis scraper.

Identical crawl shape to Matchi Padel (matchi/padel/scraper.py) -- overrides
ScraperCoroutines to iterate over dates rather than the usual (venue x date)
product, reusing the shared MatchiSlotFetcher, just constructed with the
tennis sport_id/category/facility-id map instead of padel's.

sport=1 is confirmed valid from live page source (the sport-picker markup on
real Matchi tennis venues) and behaviourally (sport=1/2 both return the normal
"not available" HTML fragment rather than a broken response), but neither
venue probed had online tennis booking enabled to guests at the time of
research -- one is not enabled for online booking, the other is members-only.
So this crawler is correctly wired but may return zero real slots until a
guest-bookable Matchi tennis venue is found. No fabricated price is used
(default_price="N/A") since no real tennis pricing has been observed live --
do not copy padel's hardcoded "£55.00", which is a padel-specific guess.

Matchi's proxy fallback (get_with_proxy_fallback_on_403, inherited unchanged
via MatchiSlotFetcher) already respects USE_PROXIES globally -- it is
currently disabled (exhausted Webshare free tier), so this runs fully
unproxied, identical to Matchi padel today.

Usage (pipeline):
    coroutines(search_dates)  ->  coroutine yielding List[UnifiedParserSchema]

Direct run:
    python -m sportscanner.crawlers.parsers.matchi.tennis.scraper
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Coroutine, Dict, List, Any

from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.crawlers.anonymize.proxies import httpxAsyncClient
from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.core.interfaces import BaseCrawler
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.matchi.core.strategy import (
    MatchiTennisRequestStrategy,
    MatchiResponseParserStrategy,
    MatchiSlotFetcher,
    MATCHI_ORGANISATION_WEBSITE,
    TENNIS_SPORT_ID,
    TENNIS_SLUG_TO_FACILITY_ID,
)
from sportscanner.logger import logging
from sportscanner.utils import async_timer
from sportscanner.variables import settings
from rich import print


class MatchiTennisCrawler(BaseCrawler):
    def __init__(self):
        self._fetcher = MatchiSlotFetcher(
            sport_id=TENNIS_SPORT_ID,
            category="Tennis",
            facility_ids=TENNIS_SLUG_TO_FACILITY_ID,
            default_price="N/A",
        )
        super().__init__(
            request_strategy=MatchiTennisRequestStrategy(),
            response_parser_strategy=MatchiResponseParserStrategy(),
            organisation_website=MATCHI_ORGANISATION_WEBSITE,
        )

    @async_timer
    async def _crawl_async(
        self,
        sports_venues: List[SportsVenue],
        dates: List[date],
    ) -> List[UnifiedParserSchema]:
        venue_by_slug: Dict[str, SportsVenue] = {v.slug: v for v in sports_venues}
        logging.info(
            f"Matchi: crawling {len(dates)} dates against "
            f"{len(venue_by_slug)} registered tennis venues"
        )
        semaphore = asyncio.Semaphore(
            settings.CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER
        )
        async with httpxAsyncClient() as client:
            tasks = [
                self._fetcher.crawl_date(client, d, venue_by_slug, semaphore)
                for d in dates
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_slots: List[UnifiedParserSchema] = []
        for r in results:
            if isinstance(r, Exception):
                logging.error(f"Matchi tennis date task raised an exception: {r}")
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


def coroutines(
    search_dates: List[date],
) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
    """Entry point for pipeline.py: returns a coroutine suitable for SportscannerCrawlerBot."""
    crawler = MatchiTennisCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="tennis")
    if not venues:
        logging.warning("Matchi: no tennis venues found in DB, skipping")

        async def _empty():
            return []

        return _empty()
    return crawler.ScraperCoroutines(venues, search_dates)


if __name__ == "__main__":
    _dates = [date.today() + timedelta(days=i) for i in range(3)]
    print(f"Matchi tennis test run for dates: {_dates}")
    crawler = MatchiTennisCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="tennis")
    if not venues:
        print(
            "[yellow]No tennis venues in DB.  Add entries to venues.json first.[/yellow]"
        )
    else:
        results = asyncio.run(crawler._crawl_async(venues, _dates))
        print(f"Results ({len(results)} slots):")
        for r in results:
            print(r)
