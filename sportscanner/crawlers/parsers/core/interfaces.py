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


class _CircuitBreaker:
    """Tracks failure rate for one provider within a single _send_concurrent_requests
    run. Once at least `min_sample` requests have completed and the failure rate is
    at or above `failure_rate_threshold`, it trips: remaining not-yet-started requests
    short-circuit to an empty result instead of hitting the network, and in-flight
    ones are cancelled. Stops a dead/blocked provider from burning its full request
    budget (and wall-clock time) once it is already clear the provider is down, rather
    than firing every remaining request only to get empty or failed responses.

    "Failure" here means a connection-level error or a 5xx from the origin - both
    signal something is wrong with the provider itself. A 4xx (venue doesn't publish
    this activity/duration) is not counted; that is expected, per-request behaviour,
    not a provider health signal.
    """

    def __init__(self, min_sample: int = 20, failure_rate_threshold: float = 0.5):
        self.min_sample = min_sample
        self.failure_rate_threshold = failure_rate_threshold
        self.completed = 0
        self.failures = 0
        self.tripped = False

    def record(self, failed: bool) -> None:
        self.completed += 1
        if failed:
            self.failures += 1
        if (
            not self.tripped
            and self.completed >= self.min_sample
            and (self.failures / self.completed) >= self.failure_rate_threshold
        ):
            self.tripped = True


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
        # Set fresh at the start of each _send_concurrent_requests call (a new
        # BaseCrawler subclass instance is created per pipeline run, so this never
        # carries state across runs).
        self._circuit_breaker: Optional[_CircuitBreaker] = None

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

        Records each outcome against `self._circuit_breaker` (connection errors and
        5xx count as failures; 4xx and genuine successes/empty-responses do not) —
        see `_CircuitBreaker` and `_send_concurrent_requests`.
        """
        breaker = self._circuit_breaker
        if breaker is not None and breaker.tripped:
            return []

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
                    if breaker is not None:
                        breaker.record(failed=False)
                    return self._on_empty_response(request_details)
                raw_data_obj = RawResponseData(
                    content=content,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    requestMetadata=request_details,
                )
                if breaker is not None:
                    breaker.record(failed=False)
                return parser.parse(raw_data_obj)
            except httpx.HTTPStatusError as e:
                last_http_error = e
                continue  # try next fallback URL variant, if any
            except Exception as e:
                # Connection-level failures (ConnectError, ReadTimeout, resets) frequently
                # carry an empty str(e), which used to log as a blank message. Log the
                # exception type + repr so these are actually diagnosable, and keep them at
                # ERROR since an unreachable host is a real, actionable problem.
                logging.error(f"Fetch failed for {attempt_url}: {type(e).__name__}: {e!r}")
                if breaker is not None:
                    breaker.record(failed=True)
                return []
        # Every URL variant returned an HTTP error status. This is an upstream response,
        # not a crawler fault, so it shouldn't be logged at ERROR (which should mean
        # "look at this"). Split by class:
        #   4xx  -> expected: the venue doesn't publish this activity/duration for the
        #           requested window (Better/GLL's canned 422 "date not within valid days").
        #           Not a provider health signal - doesn't count against the circuit breaker.
        #   5xx  -> upstream server error worth noticing (e.g. Better's broken pickleball v2).
        #           Does count against the circuit breaker.
        status = last_http_error.response.status_code if last_http_error is not None else None
        is_client_error = status is not None and 400 <= status < 500
        if breaker is not None:
            breaker.record(failed=not is_client_error)
        if is_client_error:
            logging.debug(
                f"No data ({status}) for {request_details.url} "
                f"(tried {len(urls_to_try)} URL variant(s)) — activity not offered for this window"
            )
        else:
            logging.warning(
                f"Upstream error ({status}) for {request_details.url} "
                f"(tried {len(urls_to_try)} URL variant(s))"
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
        self._circuit_breaker = _CircuitBreaker()

        async def _bounded(
                task: Coroutine[Any, Any, List[UnifiedParserSchema]]
        ) -> List[UnifiedParserSchema]:
            try:
                async with semaphore:
                    return await task
            except asyncio.CancelledError:
                # If cancelled while still queued on the semaphore (circuit breaker
                # tripped before this task got its turn), `task` was never started —
                # close it explicitly so Python doesn't warn about an abandoned
                # never-awaited coroutine. A no-op if `task` already ran/finished.
                task.close()
                raise

        async with httpxAsyncClient() as client:
            for sports_venue, fetch_date in parameter_sets:
                item_tasks = await self._create_tasks_for_item(client, sports_venue, fetch_date)
                all_tasks.extend(item_tasks)

            logging.info(
                f"Total number of concurrent request tasks for {self.organisation_website} : {len(all_tasks)}"
            )

            # Tracked as real asyncio.Task objects (not bare coroutines) so that if the
            # circuit breaker trips partway through, the remaining not-yet-completed
            # tasks can be cancelled outright instead of left to run to completion.
            pending = {asyncio.ensure_future(_bounded(task)) for task in all_tasks}
            successful_responses: List[List[UnifiedParserSchema]] = []
            completed_count = 0
            breaker_tripped_at: Optional[int] = None
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for fut in done:
                    completed_count += 1
                    exc = fut.exception()
                    if exc is not None:
                        logging.error(f"Task {completed_count} failed with error: {exc}")
                    else:
                        successful_responses.append(fut.result())
                if self._circuit_breaker.tripped and pending:
                    breaker_tripped_at = completed_count
                    logging.warning(
                        f"{self.organisation_website}: circuit breaker tripped "
                        f"({self._circuit_breaker.failures}/{self._circuit_breaker.completed} requests failed) "
                        f"— cancelling {len(pending)} remaining request(s) instead of burning the full budget"
                    )
                    for fut in pending:
                        fut.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    break

            flattened_responses = list(itertools.chain.from_iterable(successful_responses))

            # One-line health summary per provider. A failed request returns [], so a
            # provider coming back all-empty is the signal worth surfacing (upstream
            # outage / IP block, or withdrawn activity) rather than inferring it from a
            # wall of per-request WARNINGs above.
            total = len(all_tasks)
            with_data = sum(1 for r in successful_responses if r)
            if breaker_tripped_at is not None:
                logging.warning(
                    f"{self.organisation_website}: {with_data}/{total} requests returned data "
                    f"(stopped early after {breaker_tripped_at} via circuit breaker)"
                )
            elif total and with_data == 0:
                logging.warning(
                    f"{self.organisation_website}: 0/{total} requests returned data "
                    f"— likely upstream outage, IP block, or withdrawn activity"
                )
            else:
                logging.info(
                    f"{self.organisation_website}: {with_data}/{total} requests returned data"
                )
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
            self, search_dates: List[date], sport: str, delta: Optional[int] = 6
    ) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
        """Pipeline entry point: narrow dates, resolve this provider's venues for
        `sport`, and return the scrape coroutine. Returns an empty list when the
        provider has no venues for the sport (nothing to await). Pass `delta=None`
        to crawl every requested date (providers whose API has no per-venue date
        window, e.g. EveryoneActive / Southwark)."""
        if delta is None:
            allowable_search_dates = search_dates
        else:
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
