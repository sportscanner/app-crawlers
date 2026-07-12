from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.crawlers.parsers.core.schemas import RequestDetailsWithMetadata, AdditionalRequestMetadata, \
    RawResponseData
from sportscanner.crawlers.parsers.core.interfaces import AbstractRequestStrategy, BaseCrawler
from datetime import date
from typing import Any, Coroutine, List, Optional
import asyncio
import itertools
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import HTTPError as CurlHTTPError
from sportscanner.crawlers.helpers import override

from sportscanner.logger import logging

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.citysports.core.strategy import CitySportsResponseParserStrategy
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.utils import formatted_date_list, \
    filter_for_allowable_search_dates_for_venue, validate_api_response
from sportscanner.variables import settings
from rich import print

class CitySportsBadmintonRequestStrategy(AbstractRequestStrategy):
    """
    If there are multiple variations like badminton-40 / badminton-60 min, add those here
    These should be all possible requests for a particular venue
    """
    @override
    def generate_request_details(
            self, sports_venue: SportsVenue, fetch_date: date, token: Optional[str] = None
    ) -> List[RequestDetailsWithMetadata]:
        request_generator_list = []
        formatted_date: str = fetch_date.strftime("%Y/%m/%d")
        url = (
            f"https://bookings.citysport.org.uk/LhWeb/en/api/Sites/1/Timetables/ActivityBookings"
            f"?date={formatted_date}&pid=0"
        )
        logging.debug(url)
        headers = {
            "Referer": "https://bookings.citysport.org.uk/LhWeb/en/Public/Bookings",
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
                    booking_url="https://bookings.citysport.org.uk/LhWeb/en/Public/Bookings/",
                    sportsCentre=sports_venue
                )
            )
        )
        return request_generator_list


class CitySportsCrawler(BaseCrawler):
    """CitySport sits behind a WAF that fingerprints the TLS handshake itself
    (JA3), not just headers - a plain httpx/curl-less client gets the
    connection reset mid-handshake before any HTTP request is even sent,
    regardless of User-Agent. curl_cffi impersonates a real browser's TLS
    fingerprint and gets a clean 200. This is why CitySport bypasses
    BaseCrawler's shared `_send_concurrent_requests` fetch loop (which is
    hardwired to httpx) and overrides `ScraperCoroutines` directly, same
    pattern Matchi/Playtomic use for their own reasons. See
    `docs/clubs/citysport.md` for how this was diagnosed.
    """

    def __init__(self):
        super().__init__(
            request_strategy = CitySportsBadmintonRequestStrategy(),
            response_parser_strategy = CitySportsResponseParserStrategy(),
            organisation_website = "https://citysport.org.uk"
        )

    async def _fetch_venue_date(
            self,
            session: AsyncSession,
            sports_venue: SportsVenue,
            fetch_date: date,
            semaphore: asyncio.Semaphore,
    ) -> List[UnifiedParserSchema]:
        request_details_list = self.request_strategy.generate_request_details(
            sports_venue=sports_venue, fetch_date=fetch_date
        )
        results: List[UnifiedParserSchema] = []
        for request_details in request_details_list:
            try:
                async with semaphore:
                    response = await session.get(
                        request_details.url,
                        headers=request_details.headers,
                        impersonate="chrome124",
                        timeout=30,
                    )
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                validated_response = validate_api_response(response, content_type, request_details.url)
                if not validated_response:
                    continue
                raw_data_obj = RawResponseData(
                    content=validated_response,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    requestMetadata=request_details,
                )
                results.extend(self.response_parser_strategy.parse(raw_data_obj))
            except CurlHTTPError as e:
                status = e.response.status_code if e.response is not None else None
                logging.debug(
                    f"No data ({status}) for {request_details.url} — "
                    f"activity not offered for this window"
                )
            except Exception as e:
                logging.error(f"CitySport fetch failed for {request_details.url}: {type(e).__name__}: {e!r}")
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
            f"CitySport: crawling {len(sports_venues)} venue(s) across {len(dates)} dates "
            f"via curl_cffi (TLS-fingerprint impersonation). Total parameter sets: {len(parameter_sets)}"
        )
        semaphore = asyncio.Semaphore(settings.CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER)
        async with AsyncSession() as session:
            tasks = [
                self._fetch_venue_date(session, venue, fetch_date, semaphore)
                for venue, fetch_date in parameter_sets
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_slots: List[UnifiedParserSchema] = []
        for r in results:
            if isinstance(r, Exception):
                logging.error(f"CitySport task raised: {r}")
            elif r:
                all_slots.extend(r)
        return all_slots


def run(
    crawler: BaseCrawler,
    search_dates: List[date],
    sport_venues_composite_ids: List[str]
) -> List[UnifiedParserSchema]:

    allowable_search_dates = filter_for_allowable_search_dates_for_venue(search_dates, delta=6)
    logging.warning(
        f"Search dates for crawler narrowed down to: {formatted_date_list(allowable_search_dates)}"
    )
    sport_venues_to_crawl: List[
        SportsVenue] = crawler.query_sport_venues_details(sport_venues_composite_ids)
    if not sport_venues_to_crawl:
        logging.warning(f"No item contexts found for identifiers: {sport_venues_composite_ids} for this crawler.")
        return []
    return crawler.crawl(sport_venues_to_crawl, allowable_search_dates)


def coroutines(search_dates: List[date]):
    return CitySportsCrawler().coroutines(search_dates, sport="badminton", delta=6)


if __name__ == "__main__":
    logging.info("Mocking up input data (user inputs) for pipeline")
    _dates = [
        date(2025, 5, 27)
    ]
    _sport_venues_composite_ids = ["99434b56"]
    logging.info(f"Running CitySportsCrawler crawler for slugs: {_sport_venues_composite_ids}")
    parsedResults = run(
        crawler = CitySportsCrawler(),
        search_dates = _dates,
        sport_venues_composite_ids = _sport_venues_composite_ids
    )
    print(parsedResults)
    logging.success(f"CitySportsCrawler finished. Got {len(parsedResults)} results.")
