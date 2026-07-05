import asyncio
import itertools
from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Coroutine, List, Optional, Tuple

import httpx
from sqlalchemy import any_
from sqlmodel import col, select

import sportscanner.storage.postgres.database as db
import sportscanner.storage.postgres.tables
from sportscanner.crawlers.anonymize.proxies import httpxAsyncClient
from sportscanner.crawlers.parsers.core.schemas import (
    RawResponseData,
    RequestDetailsWithMetadata,
    UnifiedParserSchema,
)
from sportscanner.crawlers.parsers.utils import (
    filter_for_allowable_search_dates_for_venue,
    formatted_date_list,
    validate_api_response,
)
from sportscanner.logger import logging
from sportscanner.utils import async_timer, timeit
from sportscanner.variables import settings

SportsVenue = sportscanner.storage.postgres.tables.SportsVenue


# Strategy Interfaces
class AbstractRequestStrategy(ABC):
    """
    If there are multiple variations like badminton-40 / badminton-60 min, add those here
    These should be all possible requests for a particular venue
    """
    @abstractmethod
    def generate_request_details(
            self, sports_venue: SportsVenue, fetch_date: date, token: Optional[str] = None
    ) -> List[RequestDetailsWithMetadata]:
        """
        Generates one or more RequestDetailsWithMetadata objects for a given context.
        'context' could be a sports_centre, hyperlinksAndMetadata, etc.
        Returns a list because one context item might lead to multiple API calls (e.g., different activities).
        """
        pass


class AbstractResponseParserStrategy(ABC):
    @abstractmethod
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        """Parses the raw response content into a list of UnifiedParserSchema objects."""
        pass


class BaseCrawler(ABC):
    """Template for a provider crawler.

    A concrete provider only needs to supply an `AbstractRequestStrategy`
    (how to build the HTTP request(s) for a venue/date) and an
    `AbstractResponseParserStrategy` (how to map the raw response into
    `UnifiedParserSchema`).  The fetch → validate → parse plumbing, concurrency
    capping, retries-via-fallback-URL and error handling all live here so they
    stay consistent across every provider.

    Providers whose API differs slightly override the small hooks below rather
    than reimplementing the fetch loop:
      * `_auth_token`        - supply a bearer/session token per request batch
      * `_extract_content`   - pull the slot payload out of the validated body
      * `_is_empty_content`  - decide what counts as "no slots in this response"
      * `_on_empty_response` - what to return when the response has no slots
    """

    def __init__(
            self,
            request_strategy: AbstractRequestStrategy,
            response_parser_strategy: AbstractResponseParserStrategy,
            organisation_website: str
    ):
        self.request_strategy = request_strategy
        self.response_parser_strategy = response_parser_strategy
        self.organisation_website = organisation_website

    # ------------------------------------------------------------------ hooks
    def _auth_token(self) -> Optional[str]:
        """Token threaded into `generate_request_details`. Default: none."""
        return None

    def _extract_content(self, validated_response: Any) -> Any:
        """Slot payload to hand to the parser. Default: the whole response body."""
        return validated_response

    def _is_empty_content(self, content: Any) -> bool:
        """Whether the extracted content carries no slots."""
        return not content

    def _on_empty_response(
            self, request_details: RequestDetailsWithMetadata
    ) -> List[UnifiedParserSchema]:
        """Result to emit when a response is fetched OK but has no slots."""
        return []

    # -------------------------------------------------------------- fetch loop
    async def _fetch_and_transform(
            self,
            client: httpx.AsyncClient,
            request_details: RequestDetailsWithMetadata,
            parser: AbstractResponseParserStrategy,
    ) -> List[UnifiedParserSchema]:
        """Fetch/validate/parse a single request, falling back across url variants.

        `request_details.url` is tried first; each entry in `fallback_urls` is
        tried in order only if the previous variant returned an HTTP error status
        (e.g. Better/GLL 422-ing a not-yet-migrated v1 or v2 endpoint). Transient
        connection-level failures are already retried inside the httpx client.
        """
        urls_to_try = [request_details.url] + (request_details.fallback_urls or [])
        last_http_error: Optional[httpx.HTTPStatusError] = None
        for attempt_url in urls_to_try:
            try:
                response = await client.get(attempt_url, headers=request_details.headers)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                validated_response = validate_api_response(response, content_type, attempt_url)
                content = self._extract_content(validated_response)
                if self._is_empty_content(content):
                    return self._on_empty_response(request_details)
                raw_data_obj = RawResponseData(
                    content=content,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    requestMetadata=request_details,
                )
                return parser.parse(raw_data_obj)
            except httpx.HTTPStatusError as e:
                last_http_error = e
                continue  # try next fallback URL variant, if any
            except Exception as e:
                logging.error(f"Error fetching/parsing {attempt_url}: {e}")
                return []
        logging.error(
            f"HTTP error for {request_details.url} "
            f"(tried {len(urls_to_try)} URL variant(s)): {last_http_error}"
        )
        return []

    async def _create_tasks_for_item(
            self, client: httpx.AsyncClient, sports_venue: SportsVenue, fetch_date: date
    ) -> List[Coroutine[Any, Any, List[UnifiedParserSchema]]]:
        """One fetch coroutine per request the strategy generates for this venue/date."""
        request_details_list = self.request_strategy.generate_request_details(
            sports_venue=sports_venue,
            fetch_date=fetch_date,
            token=self._auth_token(),
        )
        return [
            self._fetch_and_transform(client, req_details, self.response_parser_strategy)
            for req_details in request_details_list
        ]

    @async_timer
    async def _send_concurrent_requests(
            self, parameter_sets: List[Tuple[SportsVenue, date]]
    ) -> List[UnifiedParserSchema]:
        all_tasks: List[Coroutine[Any, Any, List[UnifiedParserSchema]]] = []
        # Firing hundreds of requests at once in a single burst (no pacing) causes a
        # random fraction to get connection-reset/timed-out by the origin. Cap how many
        # of this provider's requests are in flight at once to smooth that out.
        semaphore = asyncio.Semaphore(settings.CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER)

        async def _bounded(
                task: Coroutine[Any, Any, List[UnifiedParserSchema]]
        ) -> List[UnifiedParserSchema]:
            async with semaphore:
                return await task

        async with httpxAsyncClient() as client:
            for sports_venue, fetch_date in parameter_sets:
                item_tasks = await self._create_tasks_for_item(client, sports_venue, fetch_date)
                all_tasks.extend(item_tasks)

            logging.info(
                f"Total number of concurrent request tasks for {self.organisation_website} : {len(all_tasks)}"
            )
            responses = await asyncio.gather(*(_bounded(task) for task in all_tasks))
            successful_responses = []
            for idx, response in enumerate(responses):
                if isinstance(response, Exception):
                    logging.error(f"Task {idx} failed with error: {response}")
                else:
                    successful_responses.append(response)
            flattened_responses = list(itertools.chain.from_iterable(successful_responses))
        return flattened_responses

    def ScraperCoroutines(
            self, sports_venues: List[SportsVenue], dates: List[date]
    ) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
        parameter_sets: List[Tuple[SportsVenue, date]] = list(itertools.product(sports_venues, dates))
        logging.info(
            f"Crawling for {len(sports_venues)} items across {len(dates)} dates. "
            f"Total parameter sets: {len(parameter_sets)}"
        )
        return self._send_concurrent_requests(parameter_sets)

    def coroutines(
            self, search_dates: List[date], sport: str, delta: int = 6
    ) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
        """Pipeline entry point: narrow dates, resolve this provider's venues for
        `sport`, and return the scrape coroutine. Returns an empty list when the
        provider has no venues for the sport (nothing to await)."""
        allowable_search_dates = filter_for_allowable_search_dates_for_venue(search_dates, delta=delta)
        logging.warning(
            f"Search dates for crawler narrowed down to: {formatted_date_list(allowable_search_dates)}"
        )
        sport_venues_to_crawl = self.get_venues_by_sport_offering(sport=sport)
        if not sport_venues_to_crawl:
            logging.warning(
                f"No venues found for {self.organisation_website} / sport offering: {sport}"
            )
            return []
        return self.ScraperCoroutines(sport_venues_to_crawl, allowable_search_dates)

    @timeit
    def crawl(self, sports_venues: List[SportsVenue], dates: List[date]) -> List[UnifiedParserSchema]:
        if not sports_venues or not dates:
            logging.warning("No items or dates to crawl.")
            return []
        coroutines = self.ScraperCoroutines(sports_venues, dates)
        responses_from_all_sources: List[UnifiedParserSchema] = asyncio.run(coroutines)
        logging.debug(f"Unified parser schema mapped responses count: {len(responses_from_all_sources)}")
        return responses_from_all_sources

    def query_sport_venues_details(self, composite_ids: List[str]) -> List[SportsVenue]:
        """Queries database for Sports venue records against the provided composite keys"""
        if not composite_ids:
            return []
        sports_centre_lists: List[SportsVenue] = db.get_all_rows(
            db.engine,
            table=SportsVenue,
            expression=select(SportsVenue)
            .where(SportsVenue.organisation_website == self.organisation_website)
            .where(col(SportsVenue.composite_key).in_(composite_ids)),
        )
        logging.success(
            f"{len(sports_centre_lists)} Sports venue data queried from database for {self.organisation_website}"
        )
        return sports_centre_lists

    def get_venues_by_sport_offering(self, sport: str) -> List[SportsVenue]:
        """Queries database for Sports venue records against the provided Sport category"""
        sports_centre_lists: List[SportsVenue] = db.get_all_rows(
            db.engine,
            table=SportsVenue,
            expression=select(SportsVenue)
            .where(SportsVenue.organisation_website == self.organisation_website)
            .where(sport == any_(SportsVenue.sports))
        )
        logging.success(
            f"{len(sports_centre_lists)} Sports venue data queried from database for {self.organisation_website}"
        )
        return sports_centre_lists
