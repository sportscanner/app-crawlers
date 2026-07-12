from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.crawlers.parsers.core.schemas import RequestDetailsWithMetadata, AdditionalRequestMetadata, \
    RawResponseData
from sportscanner.crawlers.parsers.core.interfaces import AbstractRequestStrategy, BaseCrawler
from datetime import date, timedelta
from typing import Any, Coroutine, List, Optional, Dict
import asyncio
import itertools
import httpx
from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.anonymize.proxies import httpxAsyncClientWithProxyRotation

from sportscanner.logger import logging

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.everyoneactive.core.strategy import EveryoneActiveResponseParserStrategy
from sportscanner.crawlers.parsers.everyoneactive.core.utils import get_utc_timestamps
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.utils import validate_api_response
from sportscanner.variables import settings
class EveryoneActiveBadmintonRequestStrategy(AbstractRequestStrategy):
    """
    If there are multiple variations like badminton-40 / badminton-60 min, add those here
    These should be all possible requests for a particular venue
    """
    @override
    def generate_request_details(
            self, sports_venue: SportsVenue, fetch_date: date, token: Optional[str] = None
    ) -> List[RequestDetailsWithMetadata]:
        request_generator_list = []
        activityIds = {
            "queen-mother-sports-centre": "155BADMINTON1",
            "st-augustines-sports-centre": "156BADMINTON1",
            "reynolds-sports-centre": "119BADM050SH001",
            "moberly-sports-centre": "160BADM055SH001",
            "little-venice-sports-centre": "158BADMINTON1",
            "jubilee-community-leisure-centre": "282BADM060SH001",
            "church-street-community-leisure-centre": "270BADM060SH001",
            "academy-sport": "262BADM060SH001",
            "vale-farm-sports-centre": "101BADMINTON1",
            "greenford-sports-centre": "118BADM050SH001",
            "harrow-leisure-centre": "091BADMINT001",
            "the-centre-slough": "208BADM060SH001"
        }
        activityId = activityIds.get(sports_venue.slug, None)
        from_utc, to_utc = get_utc_timestamps(fetch_date)
        url = (
            f"https://caching.everyoneactive.com/aws/api/activity/availability?toUTC={to_utc}&activityId={activityId}&fromUTC={from_utc}&locale=en_GB"
        )
        logging.debug(url)
        headers: Dict = {
            'Host': 'caching.everyoneactive.com',
            'AuthenticationKey': 'M0bi1eProB00king$'
        }
        payload: Dict = {}
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
                    price="£18.0",
                    booking_url=f"https://www.everyoneactive.com/centre/{sports_venue.slug}/",
                    sportsCentre=sports_venue
                )
            )
        )
        return request_generator_list


class EveryoneActiveCrawler(BaseCrawler):
    """caching.everyoneactive.com blocks GitHub Actions runner IPs specifically
    (works fine locally). Routing through the rotating proxy configured in
    `crawlers/anonymize/proxies.py` gets past that, but the proxy account is a
    free Webshare plan with "No Automatic Proxy List Refreshes" - a small,
    static pool of exit IPs, some fraction of which are *already* blocklisted
    by this site's WAF and always will be (they never rotate out). Confirmed
    empirically: repeating the exact same request against the real endpoint
    gets an HTTP 403 (blocklisted pool IP) roughly 55-65% of the time and a
    clean 200 the rest, both in isolated testing and in production
    (47/120 = 39% succeeded on first try with no retry logic).

    A 403 through this proxy does NOT mean "this venue doesn't offer this
    activity" the way a 4xx means for every other provider - it means "you
    drew a blocked IP this time, try again with a different connection." That
    is a genuinely different signal specific to this provider's constrained
    proxy situation, so it's handled here rather than folded into
    `BaseCrawler`'s shared 4xx-is-expected handling, which is correct for
    every other provider and would be wrong to change.

    Bypasses `BaseCrawler`'s shared fetch loop entirely (like Matchi,
    Playtomic, CitySport) and opens a brand-new proxied client per retry
    attempt - each fresh connection is a fresh shot at the proxy's rotation,
    same as confirmed by hand with repeated standalone requests. Retrying
    against a *shared, reused* connection would not help, since Webshare's
    rotation happens at connection/tunnel setup, not per-request within one
    kept-alive connection. See `docs/clubs/everyone-active.md`.
    """

    _MAX_PROXY_ATTEMPTS = 5

    def __init__(self):
        super().__init__(
            request_strategy = EveryoneActiveBadmintonRequestStrategy(),
            response_parser_strategy = EveryoneActiveResponseParserStrategy(),
            organisation_website = "https://www.everyoneactive.com/"
        )

    async def _fetch_with_retry(
            self, request_details: RequestDetailsWithMetadata
    ) -> List[UnifiedParserSchema]:
        last_status: Optional[int] = None
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
                    return []  # a clean pool IP genuinely reporting no slots - not worth retrying
                raw_data_obj = RawResponseData(
                    content=validated_response,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    requestMetadata=request_details,
                )
                return self.response_parser_strategy.parse(raw_data_obj)
            except httpx.HTTPStatusError as e:
                last_status = e.response.status_code
                logging.debug(
                    f"EveryoneActive: {last_status} (likely a blocklisted proxy IP) for "
                    f"{request_details.url}, attempt {attempt}/{self._MAX_PROXY_ATTEMPTS}"
                )
                continue
            except Exception as e:
                logging.error(f"EveryoneActive fetch failed for {request_details.url}: {type(e).__name__}: {e!r}")
                return []
        logging.warning(
            f"EveryoneActive: exhausted {self._MAX_PROXY_ATTEMPTS} attempts (last status {last_status}) "
            f"for {request_details.url} - proxy pool may be mostly/fully blocklisted right now"
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
            f"EveryoneActive: crawling {len(sports_venues)} venue(s) across {len(dates)} dates "
            f"via rotating proxy (up to {self._MAX_PROXY_ATTEMPTS} attempts/request). "
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
                logging.error(f"EveryoneActive task raised: {r}")
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
    # delta=None: EveryoneActive's API has no per-venue date window, so crawl every requested date.
    return EveryoneActiveCrawler().coroutines(search_dates, sport="badminton", delta=None)


if __name__ == "__main__":
    logging.info("Mocking up input data (user inputs) for pipeline")
    _dates = [
        date.today() + timedelta(days=2)
    ]
    print(f"Dates to search for: {_dates}")
    _sport_venues_composite_ids = ["b03e14b9"]
    logging.info(f"Running EveryoneActiveCrawler crawler for slugs: {_sport_venues_composite_ids}")
    parsedResults = run(
        crawler = EveryoneActiveCrawler(),
        search_dates = _dates,
        sport_venues_composite_ids = _sport_venues_composite_ids
    )
    logging.success(f"EveryoneActiveCrawler finished. Got {len(parsedResults)} results.")
