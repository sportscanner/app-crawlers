from pydantic import ValidationError

import sportscanner.storage.postgres.tables
from sportscanner.crawlers.parsers.core.schemas import RawResponseData, RequestDetailsWithMetadata
from sportscanner.crawlers.parsers.core.interfaces import AbstractResponseParserStrategy, AbstractAsyncTaskCreationStrategy, AbstractRequestStrategy
from datetime import date, datetime
from typing import Any, Coroutine, List
from sportscanner.crawlers.helpers import override

import httpx
from loguru import logger as logging

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.citysports.core.schema import CitySportsResponseSchema
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.utils import validate_api_response


class CitySportsResponseParserStrategy(AbstractResponseParserStrategy):
    def _transform_raw_response_to_typed(self, api_response) -> List[CitySportsResponseSchema]:
        try:
            aligned_api_response = [
                CitySportsResponseSchema(**response_block)
                for response_block in api_response
            ]
            logging.debug(f"Data aligned with overall schema: {CitySportsResponseSchema}")
            return aligned_api_response
        except ValidationError as e:
            logging.error(f"Unable to apply CitySportsResponseSchema to raw API json:\n{e}")
            raise ValidationError

    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        if len(raw_response.content) <= 0:
            return []
        raw_response_typed: List[CitySportsResponseSchema] = self._transform_raw_response_to_typed(raw_response.content)
        unified_schema_output = []
        for slot in raw_response_typed:
            if slot.ActivityGroupDescription == "Badminton":
                unified_schema_output.append(
                    UnifiedParserSchema(
                        category=raw_response.requestMetadata.metadata.category,
                        starting_time=datetime.strptime(
                            slot.StartTime, "%Y-%m-%dT%H:%M:%S"
                        ).time(),
                        ending_time=datetime.strptime(slot.EndTime, "%Y-%m-%dT%H:%M:%S").time(),
                        date=datetime.strptime(slot.StartTime, "%Y-%m-%dT%H:%M:%S").date(),
                        price="£" + str(slot.Price),
                        spaces=slot.AvailablePlaces,
                        composite_key=raw_response.requestMetadata.metadata.sportsCentre.composite_key,
                        last_refreshed=raw_response.requestMetadata.metadata.last_refreshed,
                        booking_url=raw_response.requestMetadata.metadata.booking_url
                    )
                )
        return unified_schema_output


class CitySportsTaskCreationStrategy(AbstractAsyncTaskCreationStrategy):
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

