from pydantic import ValidationError

from sportscanner.crawlers.parsers.core.schemas import RawResponseData
from sportscanner.crawlers.parsers.core.interfaces import AbstractResponseParserStrategy
from datetime import datetime
from typing import List
from sportscanner.crawlers.helpers import override

from sportscanner.logger import logging

from sportscanner.crawlers.parsers.citysports.core.schema import CitySportsResponseSchema
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema


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

