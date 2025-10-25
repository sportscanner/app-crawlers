from abc import ABC, abstractmethod
from typing import Any, List, Tuple, Coroutine, Optional
from datetime import date
import httpx
from sqlalchemy import any_

import sportscanner.storage.postgres.tables
from sportscanner.crawlers.parsers.core.schemas import RequestDetailsWithMetadata, UnifiedParserSchema, RawResponseData
from sportscanner.logger import logging
import asyncio
import sportscanner.storage.postgres.database as db
from sqlmodel import col, select
from sportscanner.crawlers.anonymize.proxies import httpxAsyncClient
from sportscanner.utils import async_timer, timeit
import itertools # Keep this


# Strategy Interfaces
class AbstractRequestStrategy(ABC):
    """
    If there are multiple variations like badminton-40 / badminton-60 min, add those here
    These should be all possible requests for a particular venue
    """
    @abstractmethod
    def generate_request_details(
            self, sports_venue: sportscanner.storage.postgres.tables.SportsVenue, fetch_date: date, token: Optional[str] = None
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

class AbstractAsyncTaskCreationStrategy(ABC):
    @abstractmethod
    def create_tasks_for_item(self, client: httpx.AsyncClient, sports_venue: sportscanner.storage.postgres.tables.SportsVenue, fetch_date: date, request_strategy: AbstractRequestStrategy, response_parser_strategy: AbstractResponseParserStrategy) -> List[Coroutine[Any, Any, List[UnifiedParserSchema]]]:
        """
        Generates async tasks for a single item (e.g., one sports_centre or one hyperlinkSet).
        It will use the request_strategy to get URL/headers/payload.
        """
        pass


class BaseCrawler(ABC):
    def __init__(
            self,
            request_strategy: AbstractRequestStrategy,
            response_parser_strategy: AbstractResponseParserStrategy,
            task_creation_strategy: AbstractAsyncTaskCreationStrategy,
            organisation_website: str
    ):
        self.request_strategy = request_strategy
        self.response_parser_strategy = response_parser_strategy
        self.task_creation_strategy = task_creation_strategy
        self.organisation_website = organisation_website

    @async_timer
    async def _send_concurrent_requests(self, parameter_sets: List[Tuple[
        sportscanner.storage.postgres.tables.SportsVenue, date]]) -> List[UnifiedParserSchema]:
        all_tasks: List[Coroutine[Any, Any, List[UnifiedParserSchema]]] = []
        async with httpxAsyncClient() as client:
            for sports_venue, fetch_date in parameter_sets:
                # Delegate task creation for this specific item context to the strategy
                item_tasks = await self.task_creation_strategy.create_tasks_for_item(
                    client, sports_venue, fetch_date, self.request_strategy, self.response_parser_strategy
                )
                all_tasks.extend(item_tasks)

            logging.info(f"Total number of concurrent request tasks for {self.organisation_website} : {len(all_tasks)}")
            responses = await asyncio.gather(*all_tasks)
            successful_responses = []
            for idx, response in enumerate(responses):
                if isinstance(response, Exception):
                    logging.error(f"Task {idx} failed with error: {response}")
                else:
                    successful_responses.append(response)
            flattened_responses = list(itertools.chain.from_iterable(successful_responses))
        return flattened_responses


    def ScraperCoroutines(self, sports_venues: List[sportscanner.storage.postgres.tables.SportsVenue], dates: List[date]) -> Coroutine[Any, Any, list[UnifiedParserSchema]]:
        parameter_sets: List[Tuple[
            sportscanner.storage.postgres.tables.SportsVenue, date]] = list(itertools.product(sports_venues, dates))
        logging.info(
            f"Crawling for {len(sports_venues)} items across {len(dates)} dates. Total parameter sets: {len(parameter_sets)}"
        )
        return self._send_concurrent_requests(parameter_sets)

    @timeit
    def crawl(self, sports_venues: List[sportscanner.storage.postgres.tables.SportsVenue], dates: List[date]) -> List[UnifiedParserSchema]:
        if not sports_venues or not dates:
            logging.warning("No items or dates to crawl.")
            return []
        coroutines = self.ScraperCoroutines(sports_venues, dates)
        responses_from_all_sources: List[UnifiedParserSchema] = asyncio.run(
            coroutines
        )
        logging.debug(f"Unified parser schema mapped responses count: {len(responses_from_all_sources)}")
        return responses_from_all_sources

    def query_sport_venues_details(self, composite_ids: List[str]) -> List[
        sportscanner.storage.postgres.tables.SportsVenue]:
        if not composite_ids:
            return []
        """Queries database for Sports venue records against the provided composite keys"""
        sports_centre_lists: List[sportscanner.storage.postgres.tables.SportsVenue] = db.get_all_rows(
            db.engine,
            table=sportscanner.storage.postgres.tables.SportsVenue,
            expression=select(sportscanner.storage.postgres.tables.SportsVenue)
            .where(sportscanner.storage.postgres.tables.SportsVenue.organisation_website == self.organisation_website)
            .where(col(sportscanner.storage.postgres.tables.SportsVenue.composite_key).in_(composite_ids)),
        )
        logging.success(
            f"{len(sports_centre_lists)} Sports venue data queried from database for {self.organisation_website}"
        )
        return sports_centre_lists

    def get_venues_by_sport_offering(self, sport: str) -> List[sportscanner.storage.postgres.tables.SportsVenue]:
        """Queries database for Sports venue records against the provided Sport category"""
        sports_centre_lists: List[sportscanner.storage.postgres.tables.SportsVenue] = db.get_all_rows(
            db.engine,
            table=sportscanner.storage.postgres.tables.SportsVenue,
            expression=select(sportscanner.storage.postgres.tables.SportsVenue)
            .where(sportscanner.storage.postgres.tables.SportsVenue.organisation_website == self.organisation_website)
            .where(sport == any_(sportscanner.storage.postgres.tables.SportsVenue.sports))
        )
        logging.success(
            f"{len(sports_centre_lists)} Sports venue data queried from database for {self.organisation_website}"
        )
        return sports_centre_lists
