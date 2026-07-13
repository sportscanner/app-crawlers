from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.crawlers.parsers.core.schemas import RequestDetailsWithMetadata, AdditionalRequestMetadata, \
    RawResponseData
from sportscanner.crawlers.parsers.core.interfaces import AbstractRequestStrategy, BaseCrawler
from datetime import date
from typing import Any, Coroutine, List, Optional
import asyncio
import itertools
import httpx
from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.anonymize.proxies import httpxAsyncClientWithProxyRotation

from sportscanner.logger import logging

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.uelsportsdock.core.strategy import UELSportsDockResponseParserStrategy
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.utils import validate_api_response
from sportscanner.variables import settings


class UELSportsDockBadmintonRequestStrategy(AbstractRequestStrategy):
    """
    UEL SportsDock runs on the same 'Leisure Hub' (LhWeb) booking platform as
    CitySport (see sportscanner/crawlers/parsers/citysports/) - identical
    anonymous timetable API, no auth needed to view availability (only to
    complete an actual booking). Unlike CitySport, this instance is not behind
    a TLS-fingerprinting WAF, so it uses BaseCrawler's standard fetch loop
    directly rather than the curl_cffi bypass CitySport needs. See
    docs/clubs/uel-sportsdock.md.
    """
    @override
    def generate_request_details(
            self, sports_venue: SportsVenue, fetch_date: date, token: Optional[str] = None
    ) -> List[RequestDetailsWithMetadata]:
        request_generator_list = []
        formatted_date: str = fetch_date.strftime("%Y/%m/%d")
        url = (
            f"https://horizons.uel.ac.uk/LhWeb/en/api/Sites/1/Timetables/ActivityBookings"
            f"?date={formatted_date}&pid=0"
        )
        logging.debug(url)
        headers = {
            "Referer": "https://horizons.uel.ac.uk/LhWeb/en/Public/Bookings",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        }
        payload: dict = {}
        request_generator_list.append(
            RequestDetailsWithMetadata(
                url=url,
                headers=headers,
                payload=payload,
                token=None,
                cookies=None,
                metadata=AdditionalRequestMetadata(
                    category="Badminton",
                    date=fetch_date,
                    price=None,
                    booking_url="https://horizons.uel.ac.uk/LhWeb/en/Public/Bookings/",
                    sportsCentre=sports_venue
                )
            )
        )
        return request_generator_list


class UELSportsDockCrawler(BaseCrawler):
    """horizons.uel.ac.uk consistently times out (ReadTimeout, not a clean
    error status) when hit from GitHub Actions runner IPs specifically -
    confirmed 10/10 requests failing this way on the first two production
    runs after this venue was added, while the exact same request succeeds in
    well under a second from a non-GH-Actions connection. This is the same
    class of problem as Everyone Active (see docs/clubs/everyone-active.md) -
    a soft/silent block rather than a 403 - so it gets the same fix: bypass
    BaseCrawler's shared fetch loop and route through the rotating proxy with
    retry, rather than the 403-triggered fallback Matchi/Playtomic use (there's
    no clean error status here to trigger on - direct connections just hang
    until they time out, so there's no point trying direct first).

    Low request volume (1 venue, 10 requests/run) keeps this cheap on the
    shared proxy pool relative to Everyone Active's 120/run. See
    docs/clubs/uel-sportsdock.md.
    """

    _MAX_PROXY_ATTEMPTS = 4

    def __init__(self):
        super().__init__(
            request_strategy = UELSportsDockBadmintonRequestStrategy(),
            response_parser_strategy = UELSportsDockResponseParserStrategy(),
            organisation_website = "https://www.uel.ac.uk"
        )

    async def _fetch_with_retry(
            self, request_details: RequestDetailsWithMetadata
    ) -> List[UnifiedParserSchema]:
        for attempt in range(1, self._MAX_PROXY_ATTEMPTS + 1):
            try:
                async with httpxAsyncClientWithProxyRotation() as client:
                    response = await client.get(
                        request_details.url, headers=request_details.headers, timeout=15
                    )
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                validated_response = validate_api_response(response, content_type, request_details.url)
                if not validated_response:
                    return []
                raw_data_obj = RawResponseData(
                    content=validated_response,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    requestMetadata=request_details,
                )
                return self.response_parser_strategy.parse(raw_data_obj)
            except Exception as e:
                logging.debug(
                    f"UEL SportsDock: attempt {attempt}/{self._MAX_PROXY_ATTEMPTS} failed for "
                    f"{request_details.url}: {type(e).__name__}: {e!r}"
                )
        logging.warning(
            f"UEL SportsDock: exhausted {self._MAX_PROXY_ATTEMPTS} proxy attempts for "
            f"{request_details.url}"
        )
        return []

    async def _fetch_venue_date(
            self,
            sports_venue: SportsVenue,
            fetch_date: date,
            semaphore: asyncio.Semaphore,
    ) -> List[UnifiedParserSchema]:
        request_details_list = self.request_strategy.generate_request_details(
            sports_venue=sports_venue, fetch_date=fetch_date
        )
        results: List[UnifiedParserSchema] = []
        for request_details in request_details_list:
            async with semaphore:
                results.extend(await self._fetch_with_retry(request_details))
        return results

    @override
    def ScraperCoroutines(
            self, sports_venues: List[SportsVenue], dates: List[date]
    ) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
        return self._crawl_async(sports_venues, dates)

    async def _crawl_async(
            self, sports_venues: List[SportsVenue], dates: List[date]
    ) -> List[UnifiedParserSchema]:
        parameter_sets = list(itertools.product(sports_venues, dates))
        logging.info(
            f"UEL SportsDock: crawling {len(sports_venues)} venue(s) across {len(dates)} dates "
            f"via rotating proxy (direct connection times out from GitHub Actions). "
            f"Total parameter sets: {len(parameter_sets)}"
        )
        semaphore = asyncio.Semaphore(settings.CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER)
        tasks = [
            self._fetch_venue_date(venue, fetch_date, semaphore)
            for venue, fetch_date in parameter_sets
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_slots: List[UnifiedParserSchema] = []
        for r in results:
            if isinstance(r, Exception):
                logging.error(f"UEL SportsDock task raised: {r}")
            elif r:
                all_slots.extend(r)
        return all_slots


def run(
    crawler: BaseCrawler,
    search_dates: List[date],
    sport_venues_composite_ids: List[str]
) -> List[UnifiedParserSchema]:
    sport_venues_to_crawl: List[
        SportsVenue] = crawler.query_sport_venues_details(sport_venues_composite_ids)
    if not sport_venues_to_crawl:
        logging.warning(f"No item contexts found for identifiers: {sport_venues_composite_ids} for this crawler.")
        return []
    return crawler.crawl(sport_venues_to_crawl, search_dates)


def coroutines(search_dates: List[date]):
    # delta=None: no per-venue date-window narrowing needed - confirmed live
    # that this venue's API returns valid data even 3+ weeks out, unlike
    # Better/GLL-style providers that reject far-future dates with a 422.
    return UELSportsDockCrawler().coroutines(search_dates, sport="badminton", delta=None)


if __name__ == "__main__":
    from datetime import timedelta
    from rich import print
    logging.info("Mocking up input data (user inputs) for pipeline")
    _dates = [date.today() + timedelta(days=1)]
    _sport_venues_composite_ids = ["e91e28d4"]  # UEL SportsDock
    logging.info(f"Running UELSportsDockCrawler crawler for slugs: {_sport_venues_composite_ids}")
    parsedResults = run(
        crawler = UELSportsDockCrawler(),
        search_dates = _dates,
        sport_venues_composite_ids = _sport_venues_composite_ids
    )
    print(parsedResults)
    logging.success(f"UELSportsDockCrawler finished. Got {len(parsedResults)} results.")
