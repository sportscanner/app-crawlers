"""
Gladstone Go padel scraper for the multi-tenant venues.

Availability is public and anonymous: ``GET /api/samlauthentication/anonymous``
issues a Jwt cookie without a user account, then the same
``/api/availability/V2/sessions`` endpoint Mytime Active uses returns the
court grid. The parser is shared with Mytime Active; only the per-venue tenant
lookup is new.
"""

from __future__ import annotations

import asyncio
import itertools
from collections import defaultdict
from datetime import date
from typing import Any, Coroutine, Dict, List

from sportscanner.crawlers.anonymize.proxies import httpxAsyncClient
from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.core.interfaces import BaseCrawler
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.gladstonego.core.strategy import (
    GladstoneGoPadelRequestStrategy,
)
from sportscanner.crawlers.parsers.gladstonego.core.venues import (
    GLADSTONE_TENANTS,
)
from sportscanner.crawlers.parsers.mytimeactive.core.strategy import (
    GladstoneGoResponseParserStrategy,
    get_anonymous_jwt,
)
from sportscanner.logger import logging
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.variables import settings

GLADSTONE_ORGANISATION_WEBSITE = "https://www.gladstonego.cloud"


class GladstoneGoPadelCrawler(BaseCrawler):
    # The Gladstone API intermittently 500s on a valid activity/date and
    # succeeds on an immediate retry (confirmed 2026-10-30).
    retry_5xx_attempts = 2
    def __init__(self):
        super().__init__(
            request_strategy=GladstoneGoPadelRequestStrategy(),
            response_parser_strategy=GladstoneGoResponseParserStrategy(),
            organisation_website=GLADSTONE_ORGANISATION_WEBSITE,
        )

    @override
    def ScraperCoroutines(
        self, sports_venues: List[SportsVenue], dates: List[date]
    ) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
        return self._crawl_async(sports_venues, dates)

    async def _crawl_async(
        self, sports_venues: List[SportsVenue], dates: List[date]
    ) -> List[UnifiedParserSchema]:
        venues_by_host: Dict[str, List[SportsVenue]] = defaultdict(list)
        for venue in sports_venues:
            tenant = GLADSTONE_TENANTS.get(venue.slug)
            if tenant:
                venues_by_host[tenant["host"]].append(venue)
            else:
                logging.error(
                    f"Gladstone Go: no tenant mapping for {venue.slug} - skipping"
                )
        if not venues_by_host:
            return []

        tokens: Dict[str, str] = {}
        for host in venues_by_host:
            token = get_anonymous_jwt(host, log_label=host)
            if token:
                tokens[host] = token
            else:
                logging.error(f"Gladstone Go({host}): no anonymous JWT - skipping")

        semaphore = asyncio.Semaphore(
            settings.CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER
        )
        tasks = []
        async with httpxAsyncClient() as client:

            async def bounded(request_details) -> List[UnifiedParserSchema]:
                async with semaphore:
                    return await self._fetch_and_transform(
                        client, request_details, self.response_parser_strategy
                    )

            for host, venues in venues_by_host.items():
                token = tokens.get(host)
                if not token:
                    continue
                for venue, fetch_date in itertools.product(venues, dates):
                    for request_details in self.request_strategy.generate_request_details(
                        sports_venue=venue,
                        fetch_date=fetch_date,
                        token=token,
                    ):
                        tasks.append(bounded(request_details))

            logging.info(
                f"Gladstone Go: crawling {len(sports_venues)} venue(s) across "
                f"{len(dates)} date(s) on {len(tokens)} tenant host(s)"
            )
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_slots: List[UnifiedParserSchema] = []
        for result in results:
            if isinstance(result, Exception):
                logging.error(f"Gladstone Go task raised: {result!r}")
            elif result:
                all_slots.extend(result)
        return all_slots


def coroutines(search_dates: List[date]):
    return GladstoneGoPadelCrawler().coroutines(
        search_dates, sport="padel", delta=None
    )


if __name__ == "__main__":
    from rich import print

    _dates = [date.today()]
    crawler = GladstoneGoPadelCrawler()
    venue = SportsVenue(
        composite_key="00000000",
        organisation="Gladstone Go",
        organisation_website=GLADSTONE_ORGANISATION_WEBSITE,
        venue_name="Xcite Bathgate",
        slug="xcite-bathgate",
        postcode="EH48 4LA",
        address="Xcite Bathgate, Torphichen Road, Bathgate",
        latitude=55.909016,
        longitude=-3.636861,
        sports=["padel"],
    )
    results = asyncio.run(crawler.ScraperCoroutines([venue], _dates))
    print(f"Got {len(results)} slots")
    print(results[:3])
