import asyncio
import itertools
from datetime import date, timedelta
from typing import Any, Coroutine, Dict, List, Tuple

import httpx
from loguru import logger as logging
from prefect.cache_policies import NO_CACHE
from pydantic import ValidationError
from sqlmodel import col, select

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.anonymize.proxies import httpxAsyncClient
from sportscanner.crawlers.parsers.citysports.schema import CitySportsResponseSchema
from sportscanner.crawlers.parsers.schema import UnifiedParserSchema
from sportscanner.utils import async_timer, timeit
from prefect import flow, task

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


def create_async_tasks(
    client, sports_centre: db.SportsVenue, search_date: date
) -> List[Coroutine[Any, Any, List[UnifiedParserSchema]]]:
    """Generates Async task for concurrent calls to be made later"""
    tasks: List[Coroutine[Any, Any, List[UnifiedParserSchema]]] = []
    url, headers, _ = generate_api_call_params(search_date)
    tasks.append(fetch_data(client, url, headers, metadata=sports_centre))
    return tasks


def generate_api_call_params(search_date: date):
    formatted_search_date = search_date.strftime("%Y/%m/%d")
    """Generates URL, Headers and Payload information for the API curl request"""
    url = (
        f"https://bookings.citysport.org.uk/LhWeb/en/api/Sites/1/Timetables/ActivityBookings"
        f"?date={formatted_search_date}&pid=0"
    )
    logging.debug(url)
    headers = {
        "Referer": "https://bookings.citysport.org.uk/LhWeb/en/Public/Bookings",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    }
    payload: Dict = {}
    return url, headers, payload

@task(cache_policy=NO_CACHE, retries=2, name="CitySports API", persist_result=True, retry_delay_seconds=2)
@async_timer
async def fetch_data(
    client, url, headers, metadata: db.SportsVenue
) -> List[UnifiedParserSchema]:
    """Initiates request to server asynchronous using httpx"""
    response = await client.get(url, headers=headers)
    content_type = response.headers.get("content-type", "")
    match response.status_code:
        case 200:
            json_response = response.json()
            logging.debug(
                f"Request success: Raw response for url: {url} \n{json_response}"
            )
        case _:
            logging.error(
                f"Response status code is not: Response [200 OK]"
                f"\nResponse: {response}"
            )

    if len(response.json()) > 0:
        raw_responses_with_schema = apply_raw_response_schema(response.json())
        return [
            UnifiedParserSchema.from_citysports_api_response(response, metadata)
            for response in raw_responses_with_schema
            if response.ActivityGroupDescription == "Badminton"
        ]
    else:
        return []


def apply_raw_response_schema(api_response) -> List[CitySportsResponseSchema]:
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

@timeit
def get_concurrent_requests(
    sports_centre_lists: List[db.SportsVenue], search_dates: List
) -> Coroutine[Any, Any, tuple[list[UnifiedParserSchema], ...]]:
    """Runs the Async API calls, collects and standardises responses and populate distance/postal
    metadata"""
    parameter_sets: List[Tuple[db.SportsVenue, date]] = [
        (x, y) for x, y in itertools.product(sports_centre_lists, search_dates)
    ]
    logging.debug(
        f"VENUES: {[sports_centre.venue_name for sports_centre in sports_centre_lists]}"
    )
    return send_concurrent_requests(parameter_sets)


@task(name="CitySports Coroutines")
def pipeline(
    search_dates: List[date], composite_identifiers: List[str]
) -> Coroutine[Any, Any, tuple[list[UnifiedParserSchema], ...]]:
    sports_centre_lists = db.get_all_rows(
        db.engine,
        table=db.SportsVenue,
        expression=select(db.SportsVenue)
        .where(col(db.SportsVenue.composite_key).in_(composite_identifiers))
        .where(db.SportsVenue.organisation_website == "https://citysport.org.uk"),
    )
    if sports_centre_lists:
        logging.info(
            f"{len(sports_centre_lists)} CitySports venue data loaded from database"
        )
        return get_concurrent_requests(sports_centre_lists, search_dates)
    else:
        logging.warning("No query slugs matching CitySports venues")
        return []


if __name__ == "__main__":
    logging.info("Mocking up input data (user inputs) for pipeline")
    today = date.today()
    _dates = [today + timedelta(days=i) for i in range(3)]
    sports_venues: List[db.SportsVenue] = db.get_all_rows(
        db.engine,
        db.SportsVenue,
        select(db.SportsVenue).where(db.SportsVenue.organisation == "citysport.org.uk"),
    )
    venues_slugs = [sports_venue.slug for sports_venue in sports_venues]
    pipeline(_dates, venues_slugs)
