import asyncio
import itertools
from datetime import date, timedelta
from typing import Any, Coroutine, Dict, List, Tuple

import httpx
from httpx import ConnectError, HTTPError
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
                logging.warning(f"Task {idx} failed with error: {response}")
            else:
                successful_responses.append(response)
        # Flatten successful responses (removes nested list layers)
        flattened_responses = list(itertools.chain.from_iterable(successful_responses))
    return flattened_responses


def create_async_tasks(
    client, sports_centre: db.SportsVenue, fetch_date: date
) -> List[Coroutine[Any, Any, List[UnifiedParserSchema]]]:
    """Generates Async task for concurrent calls to be made later"""
    tasks: List[Coroutine[Any, Any, List[UnifiedParserSchema]]] = []
    for activity_duration in ["badminton-40min", "badminton-60min"]:
        url, headers, _ = generate_api_call_params(
            sports_centre, fetch_date, activity=activity_duration
        )
        tasks.append(fetch_data(client, url, headers, metadata=sports_centre))
    return tasks


def generate_api_call_params(
    sports_centre: db.SportsVenue, fetch_date: date, activity: str
):
    """Generates URL, Headers and Payload information for the API curl request"""
    url = (
        f"https://better-admin.org.uk/api/activities/venue/"
        f"{sports_centre.slug}/activity/{activity}/times?date={fetch_date}"
    )
    logging.debug(url)
    headers = {
        "origin": "https://bookings.better.org.uk",
        "referer": f"https://bookings.better.org.uk/location/{sports_centre.slug}/{activity}/{fetch_date}/by-time",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    }
    payload: Dict = {}
    return url, headers, payload


@async_timer
@retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
async def fetch_data(
    client, url: str, headers: Dict, metadata: db.SportsVenue
) -> List[UnifiedParserSchema]:
    """Initiates request to server asynchronous using httpx"""
    logging.debug(
        f"Fetching data from {url} with headers {headers} and metadata {metadata}"
    )
    try:
        response = await client.get(url, headers=headers)
        response.raise_for_status()  # Ensure non-200 responses are treated as exceptions
        content_type = response.headers.get("content-type", "")
        validated_response = validate_api_response(response, content_type, url)
        validated_response_data = validated_response.get("data")
        if validated_response_data is not None:
            raw_responses_with_schema = apply_raw_response_schema(validated_response_data)
            return [
                UnifiedParserSchema.from_better_api_response(response, metadata)
                for response in raw_responses_with_schema
            ]
        else:
            return []
    except HTTPError as e:
        logging.error(e)
        raise HTTPError


def apply_raw_response_schema(api_response) -> List[BetterApiResponseSchema]:
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
    allowable_search_dates = filter_search_dates_for_allowable(search_dates)
    logging.warning(
        f"Search dates for Better.Org crawler narrowed down to: {formatted_date_list(allowable_search_dates)}"
    )
    sports_centre_lists: List[db.SportsVenue] = db.get_all_rows(
        db.engine,
        table=db.SportsVenue,
        expression=select(db.SportsVenue)
        .where(col(db.SportsVenue.composite_key).in_(composite_identifiers))
        .where(db.SportsVenue.organisation_website == "https://www.better.org.uk"),
    )
    logging.info(
        f"{len(sports_centre_lists)} Better/GLL Sports venues queried from database"
    )

    return get_concurrent_requests(sports_centre_lists, allowable_search_dates)


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
