from collections import defaultdict
from itertools import chain

from pydantic import ValidationError

import sportscanner.storage.postgres.tables
from sportscanner.crawlers.parsers.core.schemas import RawResponseData, RequestDetailsWithMetadata
from sportscanner.crawlers.parsers.core.interfaces import AbstractResponseParserStrategy, AbstractAsyncTaskCreationStrategy, AbstractRequestStrategy
from datetime import date, datetime, timedelta
from typing import Any, Coroutine, List
from sportscanner.crawlers.helpers import override

import httpx
from loguru import logger as logging

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
import pytz

from sportscanner.crawlers.parsers.towerhamlets.core.authenticate import get_authorization_token
from sportscanner.crawlers.parsers.towerhamlets.core.schema import TowerHamletsResponseSchema, \
    AggregatedTowerHamletsResponse, Location, Slot
from sportscanner.crawlers.parsers.utils import validate_api_response

# Define the UTC and UK timezones
utc_zone = pytz.utc
uk_zone = pytz.timezone('Europe/London')


def round_to_nearest_minute(time_str) -> datetime:
    """rounds str date-time to datetime python object"""
    utc_time = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ")
    # Attach UTC timezone info
    utc_time = utc_zone.localize(utc_time)
    # Convert to UK local time (handles BST automatically)
    local_time = utc_time.astimezone(uk_zone)

    if local_time.second > 0:  # Round up if there are any seconds
        dt = local_time.replace(second=0) + timedelta(minutes=1)
    else:
        dt = local_time.replace(second=0)
    return dt


class TowerHamletsResponseParserStrategy(AbstractResponseParserStrategy):
    def _transform_raw_response_to_typed(self, api_response) -> List[TowerHamletsResponseSchema]:
        try:
            return [TowerHamletsResponseSchema(**x) for x in api_response]
        except ValidationError as e:
            logging.error(f"Unable to apply TowerHamletsResponseSchema to raw API json:\n{e}")
            raise ValidationError

    def aggregate_court_availability(self, data: List[Slot]) -> List[dict]:
        aggregated = defaultdict(lambda: {"available": 0})
        for entry in data:
            key = (entry.startTime, entry.endTime)
            if entry.status == "Available":
                aggregated[key]["available"] += 1

        result = [
            {"startTime": k[0], "endTime": k[1], "spaces": v["available"]}
            for k, v in aggregated.items()
        ]

        return result

    def rollup_and_aggregate_data(
            self, results: List[TowerHamletsResponseSchema],
    ) -> List[AggregatedTowerHamletsResponse]:
        rolled_up_results: List[AggregatedTowerHamletsResponse] = []
        for daily_stats in results:
            availability_spread_across_courts: List[Location] = daily_stats.locations
            slots_across_courts: List[List[Slot]] = [
                x.slots for x in availability_spread_across_courts
            ]
            flattened_list_of_slots: List[Slot] = list(
                chain.from_iterable(slots_across_courts)
            )
            aggregated: List[dict] = self.aggregate_court_availability(
                data=flattened_list_of_slots
            )
            for slot in aggregated:
                rounded_start = round_to_nearest_minute(slot.get("startTime"))
                rounded_end = round_to_nearest_minute(slot.get("endTime"))
                parsed = AggregatedTowerHamletsResponse(
                    date=datetime.strptime(daily_stats.date, "%Y-%m-%d").date(),
                    starting_time=rounded_start.time(),
                    ending_time=rounded_end.time(),
                    spaces=slot.get("spaces"),
                )
                rolled_up_results.append(parsed)
        return rolled_up_results

    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        raw_response_typed: List[TowerHamletsResponseSchema] = self._transform_raw_response_to_typed(raw_response.content)
        rolled_up_raw_responses: List[AggregatedTowerHamletsResponse] = (
            self.rollup_and_aggregate_data(raw_response_typed)
        )
        unified_schema_output = []
        for rolledUpResponse in rolled_up_raw_responses:
            formatted_date = rolledUpResponse.date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            previous_day = rolledUpResponse.date - timedelta(days=1)
            formatted_previous_day = previous_day.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            unified_schema_output.append(
                UnifiedParserSchema(
                    category=raw_response.requestMetadata.metadata.category,
                    starting_time=rolledUpResponse.starting_time,
                    ending_time=rolledUpResponse.ending_time,
                    date=rolledUpResponse.date,
                    price=raw_response.requestMetadata.metadata.price,
                    spaces=rolledUpResponse.spaces,
                    composite_key=raw_response.requestMetadata.metadata.sportsCentre.composite_key,
                    last_refreshed=raw_response.requestMetadata.metadata.last_refreshed,
                    booking_url=raw_response.requestMetadata.metadata.booking_url.format(
                        formatted_date=formatted_date,
                        formatted_previous_day=formatted_previous_day
                    )
                )
            )
        return unified_schema_output


class TowerHamletsTaskCreationStrategy(AbstractAsyncTaskCreationStrategy):
    def __init__(self):
        self.authorization_token: str = get_authorization_token()

    async def fetch_and_transform_via_response_parser(self, client: httpx.AsyncClient, request_details: RequestDetailsWithMetadata, parser: AbstractResponseParserStrategy) -> List[UnifiedParserSchema]:
        """Fetches/Parses/Transforms data to a unified schema for a single request"""
        try:
            response = await client.get(request_details.url, headers=request_details.headers) # Add payload if request_details.payload
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            validated_response = validate_api_response(response, content_type, request_details.url)
            if validated_response is not None:
                raw_data_obj = RawResponseData(
                    content=validated_response,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    requestMetadata=request_details
                )
                parsed_common_schema_response: List[UnifiedParserSchema] = parser.parse(raw_data_obj)
                return parsed_common_schema_response
            else:
                return []
        except httpx.HTTPStatusError as e:
            logging.error(f"HTTP error for {request_details.url}: {e}")
        except Exception as e:
            logging.error(f"Error fetching/parsing {request_details.url}: {e}")
        return []

    @override
    async def create_tasks_for_item(self, client: httpx.AsyncClient, sports_venue: sportscanner.storage.postgres.tables.SportsVenue, fetch_date: date, request_strategy: AbstractRequestStrategy, response_parser_strategy: AbstractResponseParserStrategy) -> List[Coroutine[Any, Any, List[UnifiedParserSchema]]]:
        tasks: List[Coroutine[Any, Any, List[UnifiedParserSchema]]] = []
        request_details_list: List[RequestDetailsWithMetadata] = request_strategy.generate_request_details(
            sports_venue=sports_venue,
            fetch_date=fetch_date,
            token = self.authorization_token
        )
        for req_details in request_details_list:
            tasks.append(self.fetch_and_transform_via_response_parser(client, req_details, response_parser_strategy))
        return tasks

