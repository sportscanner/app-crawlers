from pydantic import ValidationError

from sportscanner.crawlers.parsers.core.schemas import RawResponseData
from sportscanner.crawlers.parsers.core.interfaces import AbstractResponseParserStrategy
from typing import List
from sportscanner.crawlers.helpers import override

from sportscanner.logger import logging

from sportscanner.crawlers.parsers.decathlon.core.schema import *
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
import pytz

# Define the UTC and UK timezones
utc_zone = pytz.utc
uk_zone = pytz.timezone('Europe/London')

class DecathlonResponseParserStrategy(AbstractResponseParserStrategy):
    def _transform_raw_response_to_typed(self, api_response) -> DecathlonRawSchema:
        try:
            return DecathlonRawSchema.model_validate(api_response)
        except ValidationError as e:
            logging.error(f"Unable to apply DecathlonRawSchema to raw API json:\n{e}")
            raise ValidationError


    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        raw_response_typed: DecathlonRawSchema = self._transform_raw_response_to_typed(raw_response.content)
        activities: List[Activity] = raw_response_typed.root

        unified_schema_output = []
        for activity in activities:
            _booking_url = f"https://activities.decathlon.co.uk/en-GB/participants?sku={activity.identifier}"
            unified_schema_output.append(
                UnifiedParserSchema(
                    category=raw_response.requestMetadata.metadata.category,
                    starting_time=activity.startDate.astimezone(uk_zone).time(),
                    ending_time=activity.endDate.astimezone(uk_zone).time(),
                    date=activity.startDate.astimezone(uk_zone).date(),
                    price=f"£{activity.offers[0].price}" if activity.offers else "0.0",
                    spaces=activity.remainingAttendeeCapacity,
                    composite_key=raw_response.requestMetadata.metadata.sportsCentre.composite_key,
                    last_refreshed=raw_response.requestMetadata.metadata.last_refreshed,
                    booking_url=_booking_url
                )
            )
        return unified_schema_output

