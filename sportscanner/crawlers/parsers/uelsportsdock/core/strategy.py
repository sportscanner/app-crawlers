from pydantic import ValidationError

from sportscanner.crawlers.parsers.core.schemas import RawResponseData
from sportscanner.crawlers.parsers.core.interfaces import AbstractResponseParserStrategy
from datetime import datetime
from typing import List
from sportscanner.crawlers.helpers import override

from sportscanner.logger import logging

from sportscanner.crawlers.parsers.uelsportsdock.core.schema import UELSportsDockResponseSchema
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema


class UELSportsDockResponseParserStrategy(AbstractResponseParserStrategy):
    def _transform_raw_response_to_typed(self, api_response) -> List[UELSportsDockResponseSchema]:
        try:
            aligned_api_response = [
                UELSportsDockResponseSchema(**response_block)
                for response_block in api_response
            ]
            logging.debug(f"Data aligned with overall schema: {UELSportsDockResponseSchema}")
            return aligned_api_response
        except ValidationError as e:
            logging.error(f"Unable to apply UELSportsDockResponseSchema to raw API json:\n{e}")
            raise ValidationError

    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        if len(raw_response.content) <= 0:
            return []
        raw_response_typed: List[UELSportsDockResponseSchema] = self._transform_raw_response_to_typed(raw_response.content)
        unified_schema_output = []
        for slot in raw_response_typed:
            # Unlike CitySport (same platform, different site config), UEL files
            # badminton under a generic ActivityGroupDescription ("Court") rather
            # than a "Badminton" group - DisplayName is what actually says
            # "Badminton" here. Confirmed by inspecting a live response.
            if slot.DisplayName == "Badminton":
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
