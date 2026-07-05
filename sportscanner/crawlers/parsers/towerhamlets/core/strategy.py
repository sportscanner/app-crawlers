from collections import defaultdict
from itertools import chain

from pydantic import ValidationError

from sportscanner.crawlers.parsers.core.schemas import RawResponseData
from sportscanner.crawlers.parsers.core.interfaces import AbstractResponseParserStrategy
from datetime import datetime, timedelta
from typing import List
from sportscanner.crawlers.helpers import override

from sportscanner.logger import logging

from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
import pytz

from sportscanner.crawlers.parsers.towerhamlets.core.schema import TowerHamletsResponseSchema, \
    AggregatedTowerHamletsResponse, Location, Slot

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
            # Ensure the key exists in aggregated
            _ = aggregated[key]  
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

