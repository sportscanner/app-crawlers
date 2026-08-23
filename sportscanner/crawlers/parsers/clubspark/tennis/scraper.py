"""
ClubSpark (LTA) Tennis scraper.

ClubSpark's GetVenueSessions endpoint takes a startDate/endDate range and
returns every day in between in one call, unlike the venue x single-date
shape BaseCrawler's default fetch loop assumes -- so ScraperCoroutines is
overridden to issue one request per venue covering the whole requested date
range, the same kind of deviation Matchi/CitySport already make for their
own API shapes.

No auth required (public endpoint, confirmed via live testing). Sets a
Cloudflare __cf_bm cookie -- a realistic User-Agent plus the standard
per-provider concurrency cap keeps this well under any bot-management
threshold; no proxy needed.

Usage (pipeline):
    coroutines(search_dates) -> coroutine yielding List[UnifiedParserSchema]

Direct run:
    python -m sportscanner.crawlers.parsers.clubspark.tennis.scraper
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Coroutine, List

import httpx
from rich import print

from sportscanner.crawlers.anonymize.proxies import (
    get_with_proxy_fallback_on_403,
    httpxAsyncClient,
)
from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.clubspark.core.strategy import (
    CLUBSPARK_ORGANISATION_WEBSITE,
    ClubSparkTennisRequestStrategy,
    ClubSparkTennisResponseParserStrategy,
    referer_for_slug,
)
from sportscanner.crawlers.parsers.core.interfaces import BaseCrawler
from sportscanner.crawlers.parsers.core.schemas import (
    RawResponseData,
    UnifiedParserSchema,
)
from sportscanner.crawlers.parsers.utils import validate_api_response
from sportscanner.logger import logging
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.utils import async_timer
from sportscanner.variables import settings


class ClubSparkTennisCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(
            request_strategy=ClubSparkTennisRequestStrategy(),
            response_parser_strategy=ClubSparkTennisResponseParserStrategy(),
            organisation_website=CLUBSPARK_ORGANISATION_WEBSITE,
        )

    async def _fetch_venue(
        self,
        client: httpx.AsyncClient,
        sports_venue: SportsVenue,
        start_date: date,
        end_date: date,
        semaphore: asyncio.Semaphore,
    ) -> List[UnifiedParserSchema]:
        request_details_list = self.request_strategy.generate_request_details(
            sports_venue=sports_venue, fetch_date=start_date
        )
        results: List[UnifiedParserSchema] = []
        for request_details in request_details_list:
            try:
                async with semaphore:
                    response = await get_with_proxy_fallback_on_403(
                        client=client,
                        url=request_details.url,
                        params={
                            "resourceID": "",
                            "startDate": start_date.isoformat(),
                            "endDate": end_date.isoformat(),
                            "roleId": "",
                        },
                        headers={
                            **request_details.headers,
                            "referer": referer_for_slug(sports_venue.slug),
                        },
                        timeout=30,
                        log_label=f"ClubSpark({sports_venue.slug})",
                    )
                if response is None:
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                validated_response = validate_api_response(
                    response, content_type, request_details.url
                )
                if not validated_response:
                    continue
                raw_data_obj = RawResponseData(
                    content=validated_response,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    requestMetadata=request_details,
                )
                results.extend(self.response_parser_strategy.parse(raw_data_obj))
            except httpx.HTTPStatusError as e:
                logging.debug(
                    f"No data ({e.response.status_code}) for {sports_venue.slug} "
                    f"-- venue may not offer tennis in this window"
                )
            except Exception as e:
                logging.error(
                    f"ClubSpark fetch failed for {sports_venue.slug}: {type(e).__name__}: {e!r}"
                )
        return results

    @override
    def ScraperCoroutines(
        self, sports_venues: List[SportsVenue], dates: List[date]
    ) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
        return self._crawl_async(sports_venues, dates)

    @async_timer
    async def _crawl_async(
        self, sports_venues: List[SportsVenue], dates: List[date]
    ) -> List[UnifiedParserSchema]:
        start_date, end_date = min(dates), max(dates)
        logging.info(
            f"ClubSpark: crawling {len(sports_venues)} venue(s) for {start_date}..{end_date} "
            f"(one request per venue covering the whole range)"
        )
        semaphore = asyncio.Semaphore(
            settings.CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER
        )
        async with httpxAsyncClient() as client:
            tasks = [
                self._fetch_venue(client, venue, start_date, end_date, semaphore)
                for venue in sports_venues
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_slots: List[UnifiedParserSchema] = []
        for r in results:
            if isinstance(r, Exception):
                logging.error(f"ClubSpark venue task raised: {r}")
            elif r:
                all_slots.extend(r)
        return all_slots


def coroutines(
    search_dates: List[date],
) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
    """Entry point for pipeline.py -- returns a coroutine suitable for SportscannerCrawlerBot."""
    crawler = ClubSparkTennisCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="tennis")
    if not venues:
        logging.warning("ClubSpark: no tennis venues found in DB -- skipping")

        async def _empty():
            return []

        return _empty()
    return crawler.ScraperCoroutines(venues, search_dates)


if __name__ == "__main__":
    _dates = [date.today() + timedelta(days=i) for i in range(3)]
    print(f"ClubSpark tennis test run for dates: {_dates}")
    crawler = ClubSparkTennisCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="tennis")
    if not venues:
        print(
            "[yellow]No tennis venues in DB for ClubSpark. Add entries to venues.json first.[/yellow]"
        )
    else:
        results = asyncio.run(crawler._crawl_async(venues, _dates))
        print(f"Results ({len(results)} slots):")
        for r in results:
            print(r)
