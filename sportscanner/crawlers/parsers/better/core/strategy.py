from pydantic import ValidationError

import sportscanner.storage.postgres.tables
from sportscanner.crawlers.parsers.core.schemas import RawResponseData, RequestDetailsWithMetadata
from sportscanner.crawlers.parsers.core.interfaces import AbstractResponseParserStrategy, AbstractAsyncTaskCreationStrategy, AbstractRequestStrategy
from datetime import date, datetime
from typing import Any, Coroutine, List
from sportscanner.crawlers.helpers import override

import httpx
from sportscanner.logger import logging
from rich import print

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.better.core.schema import BetterApiResponseSchema
from sportscanner.crawlers.parsers.core.schemas import (UnifiedParserSchema)
from sportscanner.crawlers.parsers.utils import validate_api_response


class BetterLeisureResponseParserStrategy(AbstractResponseParserStrategy):
    def _transform_raw_response_to_typed(self, api_response) -> List[BetterApiResponseSchema]:
        aligned_api_response = []
        if isinstance(api_response, dict):
            try:
                aligned_api_response.extend(
                    [
                        BetterApiResponseSchema(**response_block)
                        for _key, response_block in api_response.items()
                    ]
                )
            except ValidationError as e:
                logging.error(
                    f"Unable to apply Better API response schema to raw API json:\n{e}"
                )
                logging.error(f"{api_response}")
        else:
            if len(api_response) > 0:
                try:
                    aligned_api_response.extend(
                        [
                            BetterApiResponseSchema(**response_block)
                            for response_block in api_response
                        ]
                    )
                except ValidationError as e:
                    logging.error(
                        f"Unable to apply BetterApiResponseSchema to raw API json:\n{e}"
                    )
        logging.debug(f"Data aligned with overall schema: {BetterApiResponseSchema}")
        return aligned_api_response

    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        raw_response_typed: List[BetterApiResponseSchema] = self._transform_raw_response_to_typed(raw_response.content)
        unified_schema_output = []
        for slot in raw_response_typed:
            try:
                unified_schema_output.append(
                    UnifiedParserSchema(
                        category=raw_response.requestMetadata.metadata.category,
                        starting_time=datetime.strptime(
                            slot.starts_at.format_24_hour, "%H:%M"
                        ).time(),
                        ending_time=datetime.strptime(
                            slot.ends_at.format_24_hour, "%H:%M"
                        ).time(),
                        date=raw_response.requestMetadata.metadata.date,
                        price=slot.price.formatted_amount,
                        spaces=slot.spaces,
                        composite_key=raw_response.requestMetadata.metadata.sportsCentre.composite_key,
                        last_refreshed=raw_response.requestMetadata.metadata.last_refreshed,
                        booking_url=raw_response.requestMetadata.metadata.booking_url
                    )
                )
            except ValueError as e:
                print(f"Error parsing time for slot {slot['Time']}: {e}")
        return unified_schema_output


class BetterLeisureTaskCreationStrategy(AbstractAsyncTaskCreationStrategy):
    async def fetch_and_transform_via_response_parser(self, client: httpx.AsyncClient, request_details: RequestDetailsWithMetadata, parser: AbstractResponseParserStrategy) -> List[UnifiedParserSchema]:
        """Fetches/Parses/Transforms data to a unified schema for a single request"""
        try:
            response = await client.get(request_details.url, headers=request_details.headers) # Add payload if request_details.payload
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            validated_response = validate_api_response(response, content_type, request_details.url)
            validated_response_data = validated_response.get("data")
            if validated_response_data is not None:
                raw_data_obj = RawResponseData(
                    content=validated_response_data,
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

