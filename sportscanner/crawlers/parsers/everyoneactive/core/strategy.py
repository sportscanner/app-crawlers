from collections import defaultdict

from pydantic import ValidationError

from sportscanner.crawlers.parsers.core.schemas import RawResponseData
from sportscanner.crawlers.parsers.core.interfaces import AbstractResponseParserStrategy
from datetime import datetime, timedelta
from typing import List
from sportscanner.crawlers.helpers import override

from sportscanner.logger import logging

from sportscanner.crawlers.parsers.everyoneactive.core.schema import EveryoneActiveRawSchema, \
    AggregatedAvailabilityResponse, SlotAvailability
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
import pytz

# Define the UTC and UK timezones
utc_zone = pytz.utc
uk_zone = pytz.timezone('Europe/London')

class EveryoneActiveResponseParserStrategy(AbstractResponseParserStrategy):
    def _transform_raw_response_to_typed(self, api_response) -> EveryoneActiveRawSchema:
        try:
            return EveryoneActiveRawSchema(**api_response)
        except ValidationError as e:
            logging.error(f"Unable to apply EveryoneActiveRawSchema to raw API json:\n{e}")
            raise ValidationError

    def populate_date_and_booking_timings(self, response: EveryoneActiveRawSchema):
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

    def aggregate_court_availability(self, api_response: EveryoneActiveRawSchema) -> AggregatedAvailabilityResponse:
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
        raw_response_typed: EveryoneActiveRawSchema = self._transform_raw_response_to_typed(raw_response.content)
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

