import asyncio
import itertools
from collections import defaultdict
from datetime import date, timedelta, datetime
from typing import Any, Coroutine, Dict, List, Tuple

import httpx
from httpx import ConnectError
from loguru import logger as logging
from pydantic import ValidationError
from sqlalchemy import True_
from sqlmodel import col, select
from tenacity import retry, stop_after_attempt, wait_fixed

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.anonymize.proxies import httpxAsyncClient
from sportscanner.crawlers.parsers.better.helper import (
    filter_search_dates_for_allowable,
)
from sportscanner.crawlers.parsers.better.schema import BetterApiResponseSchema
from sportscanner.crawlers.parsers.everyoneactive.dateformatter import get_utc_timestamps
from sportscanner.crawlers.parsers.everyoneactive.schema import EveryoneActiveRawSchema, AggregatedAvailabilityResponse, \
    SlotAvailability
from sportscanner.crawlers.parsers.schema import UnifiedParserSchema
from sportscanner.crawlers.parsers.utils import (
    formatted_date_list,
    validate_api_response,
)
from sportscanner.utils import async_timer, timeit


@async_timer
async def send_concurrent_requests(
    parameter_sets: List[Tuple[db.SportsVenue, date]]
) -> Tuple[List[UnifiedParserSchema], ...]:
    """Core logic to generate Async tasks and collect responses"""
    tasks: List[Coroutine[Any, Any, List[UnifiedParserSchema]]] = []
    async with httpxAsyncClient() as client:
        for sports_centre, fetch_date in parameter_sets:
            async_tasks = create_async_tasks(client, sports_centre, fetch_date)
            tasks.extend(async_tasks)
        logging.info(f"Total number of concurrent request tasks: {len(tasks)}")
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        # Filter out exceptions
        successful_responses = []
        for idx, response in enumerate(responses):
            if isinstance(response, Exception):
                logging.error(f"Task {idx} failed with error: {response}")
            else:
                successful_responses.append(response)
        # Flatten successful responses (removes nested list layers)
        flattened_responses = list(itertools.chain.from_iterable(successful_responses))
    return flattened_responses


activityIds = {
    "queen-mother-sports-centre": "155BADMINTON1",
    "st-augustines-sports-centre": "156BADMINTON1",
    "reynolds-sports-centre": "119BADM050SH001",
    "moberly-sports-centre": "160BADM055SH001",
    "little-venice-sports-centre": "158BADMINTON1",
    "jubilee-community-leisure-centre": "282BADM060SH001",
    "church-street-community-leisure-centre": "270BADM060SH001",
    "academy-sport": "262BADM060SH001"
}


def create_async_tasks(
    client, sports_centre: db.SportsVenue, fetch_date: date
) -> List[Coroutine[Any, Any, List[UnifiedParserSchema]]]:
    """Generates Async task for concurrent calls to be made later"""
    tasks: List[Coroutine[Any, Any, List[UnifiedParserSchema]]] = []
    activityId = activityIds.get(sports_centre.slug, None)
    url, headers, _ = generate_api_call_params(
        sports_centre, fetch_date, activity=activityId
    )
    tasks.append(fetch_data(client, url, headers, metadata=sports_centre))
    return tasks


def generate_api_call_params(
    sports_centre: db.SportsVenue, fetch_date: date, activity: str
):
    """Generates URL, Headers and Payload information for the API curl request"""
    from_utc, to_utc = get_utc_timestamps(fetch_date)
    url = (
        f"https://caching.everyoneactive.com/aws/api/activity/availability?toUTC={to_utc}&activityId={activity}&fromUTC={from_utc}&locale=en_GB"
    )
    logging.debug(url)
    headers = {
        'Host': 'caching.everyoneactive.com',
        'AuthenticationKey': 'M0bi1eProB00king$',
        'Accept': 'application/json,application/json',
        'User-Agent': 'iPhone',
        'Accept-Language': 'en-GB;q=1.0',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json'
    }
    payload: Dict = {}
    return url, headers, payload



def populate_date_and_booking_timings(response: EveryoneActiveRawSchema):
    for bookableItem in response.bookableItems:
        for slot in bookableItem.slots:
            datetime_object = datetime.utcfromtimestamp(slot.datetimeUTC)
            slot.parsedDate = datetime_object.date()
            slot.parsedStartTime = datetime_object.time()
            new_dt = datetime_object + timedelta(minutes=response.duration)
            slot.parsedEndTime = new_dt.time()
    return response


def aggregate_court_availability(api_response: EveryoneActiveRawSchema) -> AggregatedAvailabilityResponse:
    # Dictionary to store aggregated available slots
    aggregated_slots = defaultdict(int)
    # Iterate over all bookable items (courts)
    for item in api_response.bookableItems:
        for slot in item.slots:
            key = (slot.parsedDate, slot.parsedStartTime, slot.parsedEndTime)
            aggregated_slots[key] += slot.availableSlots  # Summing up available slots

    aggregated_list = sorted(aggregated_slots.items(), key=lambda x: x[0])
    # Convert data into Pydantic Model
    aggregated_result: AggregatedAvailabilityResponse  = AggregatedAvailabilityResponse(
        slots=[
            SlotAvailability(slot_date=slot[0], start_time=slot[1], end_time=slot[2], available_slots=available)
            for slot, available in aggregated_list
        ]
    )
    return aggregated_result


@async_timer
@retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
async def fetch_data(
    client, url: str, headers: Dict, metadata: db.SportsVenue
) -> List[UnifiedParserSchema]:
    """Initiates request to server asynchronous using httpx"""
    logging.debug(
        f"Fetching data from url:\n {url}\n with headers:\n {headers}\n and metadata:\n {metadata}"
    )
    response = await client.get(url, headers=headers)
    response.raise_for_status()  # Ensure non-200 responses are treated as exceptions
    content_type = response.headers.get("Content-Type", "")
    validated_response = validate_api_response(response, content_type, url)
    booking_duration = validated_response.get("duration", 60)
    if validated_response is not None:
        raw_responses_with_schema: EveryoneActiveRawSchema = apply_raw_response_schema(validated_response)
        metadata_populated_response = populate_date_and_booking_timings(raw_responses_with_schema)
        aggregated_result: AggregatedAvailabilityResponse = aggregate_court_availability(metadata_populated_response)
        return [
            UnifiedParserSchema.from_everyoneActive_rolledup_response(response, metadata, slotAvailability) for
            slotAvailability in aggregated_result.slots
        ]
    else:
        return []


def apply_raw_response_schema(api_response) -> EveryoneActiveRawSchema:
    try:
        return EveryoneActiveRawSchema(**api_response)
    except ValidationError as e:
        logging.error(f"Unable to apply EveryoneActiveRawSchema to raw API json:\n{e}")
        raise ValidationError


@timeit
def get_concurrent_requests(
    sports_centre_lists: List[db.SportsVenue], dates: List[date]
) -> Coroutine[Any, Any, tuple[list[UnifiedParserSchema], ...]]:
    """Runs the Async API calls, collects and standardises responses and populate distance/postal
    metadata"""
    parameter_sets: List[Tuple[db.SportsVenue, date]] = [
        (x, y) for x, y in itertools.product(sports_centre_lists, dates)
    ]
    logging.debug(
        f"VENUES: {[sports_centre.venue_name for sports_centre in sports_centre_lists]}"
    )
    return send_concurrent_requests(parameter_sets)


def pipeline(
    search_dates: List[date], composite_identifiers: List[str]
) -> Coroutine[Any, Any, tuple[list[UnifiedParserSchema], ...]]:
    sports_centre_lists: List[db.SportsVenue] = db.get_all_rows(
        db.engine,
        table=db.SportsVenue,
        expression=select(db.SportsVenue)
        .where(col(db.SportsVenue.composite_key).in_(composite_identifiers))
        .where(db.SportsVenue.organisation_website == "https://www.everyoneactive.com/"),
    )
    logging.info(
        f"{len(sports_centre_lists)} Everyone Active Sports venues queried from database"
    )

    return get_concurrent_requests(sports_centre_lists, search_dates)


if __name__ == "__main__":
    logging.info("Mocking up input data (user inputs) for pipeline")
    today = date.today()
    _dates = [today + timedelta(days=i) for i in range(3)]
    sports_venues: List[db.SportsVenue] = db.get_all_rows(
        db.engine,
        db.SportsVenue,
        select(db.SportsVenue).where(db.SportsVenue.organisation == "better.org.uk"),
    )
    venues_slugs = [sports_venue.slug for sports_venue in sports_venues]
    pipeline(_dates, venues_slugs[:4])
