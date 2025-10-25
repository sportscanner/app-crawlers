from collections import defaultdict

from pydantic import ValidationError

import sportscanner.storage.postgres.tables
from sportscanner.crawlers.parsers.core.schemas import RawResponseData, RequestDetailsWithMetadata
from sportscanner.crawlers.parsers.core.interfaces import AbstractResponseParserStrategy, AbstractAsyncTaskCreationStrategy, AbstractRequestStrategy
from datetime import date, datetime, timedelta
from typing import Any, Coroutine, List
from sportscanner.crawlers.helpers import override

import httpx
from sportscanner.logger import logging

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.southwarkleisure.core.schema import SouthwarkLeisureRawSchema, \
    AggregatedAvailabilityResponse, SlotAvailability
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
import pytz

from sportscanner.crawlers.parsers.utils import validate_api_response

# Define the UTC and UK timezones
utc_zone = pytz.utc
uk_zone = pytz.timezone('Europe/London')

class SouthwarkLeisureResponseParserStrategy(AbstractResponseParserStrategy):
    def _transform_raw_response_to_typed(self, api_response) -> SouthwarkLeisureRawSchema:
        try:
            return SouthwarkLeisureRawSchema(**api_response)
        except ValidationError as e:
            logging.error(f"Unable to apply SouthwarkLeisureRawSchema to raw API json:\n{e}")
            raise ValidationError

    def populate_date_and_booking_timings(self, response: SouthwarkLeisureRawSchema):
        for bookableItem in response.bookableItems:
            for slot in bookableItem.slots:
                # Convert the UTC timestamp to a timezone-aware datetime object in UTC
                utc_time = datetime.utcfromtimestamp(slot.datetimeUTC).replace(tzinfo=utc_zone)
                # Convert the UTC time to the UK's local time
                local_time = utc_time.astimezone(uk_zone)
                slot.parsedDate = local_time.date()
                slot.parsedStartTime = local_time.time()
                end_time = local_time + timedelta(minutes=response.duration)
                slot.parsedEndTime = end_time.time()
        return response

    def aggregate_court_availability(self, api_response: SouthwarkLeisureRawSchema) -> AggregatedAvailabilityResponse:
        # Dictionary to store aggregated available slots
        aggregated_slots = defaultdict(int)
        # Iterate over all bookable items (courts)
        for item in api_response.bookableItems:
            for slot in item.slots:
                key = (slot.parsedDate, slot.parsedStartTime, slot.parsedEndTime)
                aggregated_slots[key] += slot.availableSlots  # Summing up available slots

        aggregated_list = sorted(aggregated_slots.items(), key=lambda x: x[0])
        # Convert data into Pydantic Model
        aggregated_result: AggregatedAvailabilityResponse = AggregatedAvailabilityResponse(
            slots=[
                SlotAvailability(slot_date=slot[0], start_time=slot[1], end_time=slot[2], available_slots=available)
                for slot, available in aggregated_list
            ]
        )
        return aggregated_result

    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        raw_response_typed: SouthwarkLeisureRawSchema = self._transform_raw_response_to_typed(raw_response.content)
        metadata_populated_response = self.populate_date_and_booking_timings(raw_response_typed)
        aggregated_result: AggregatedAvailabilityResponse = self.aggregate_court_availability(metadata_populated_response)

        unified_schema_output = []
        for slotAvailability in aggregated_result.slots:
            unified_schema_output.append(
                UnifiedParserSchema(
                    category=raw_response.requestMetadata.metadata.category,
                    starting_time=slotAvailability.start_time,
                    ending_time=slotAvailability.end_time,
                    date=raw_response.requestMetadata.metadata.date,
                    price=raw_response.requestMetadata.metadata.price,
                    spaces=slotAvailability.available_slots,
                    composite_key=raw_response.requestMetadata.metadata.sportsCentre.composite_key,
                    last_refreshed=raw_response.requestMetadata.metadata.last_refreshed,
                    booking_url=raw_response.requestMetadata.metadata.booking_url
                )
            )
        return unified_schema_output


class SouthwarkLeisureTaskCreationStrategy(AbstractAsyncTaskCreationStrategy):
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
            token = None
        )
        for req_details in request_details_list:
            tasks.append(self.fetch_and_transform_via_response_parser(client, req_details, response_parser_strategy))
        return tasks

