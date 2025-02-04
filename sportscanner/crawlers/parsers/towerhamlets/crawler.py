import asyncio
import itertools
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from itertools import chain
from typing import Any, Coroutine, Dict, List, Optional, Tuple

import httpx
from loguru import logger as logging
from pydantic import BaseModel, ValidationError
from rich import print
from sqlmodel import col, select
from tenacity import retry, stop_after_attempt, wait_fixed

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.anonymize.proxies import httpxAsyncClient
from sportscanner.crawlers.helpers import SportscannerCrawlerBot
from sportscanner.crawlers.parsers.citysports.schema import CitySportsResponseSchema
from sportscanner.crawlers.parsers.schema import UnifiedParserSchema
from sportscanner.crawlers.parsers.towerhamlets.authenticate import (
    get_authorization_token,
)
from sportscanner.crawlers.parsers.towerhamlets.mappings import (
    HyperlinkGenerator,
    Parameters,
    siteIdsActivityIds,
)
from sportscanner.crawlers.parsers.towerhamlets.schema import (
    AggregatedTowerHamletsResponse,
    Location,
    Slot,
    TowerHamletsResponseSchema,
)
from sportscanner.crawlers.parsers.utils import validate_api_response
from sportscanner.utils import async_timer, timeit


class HyperlinkWithMetadata(BaseModel):
    siteId: str
    activityId: str
    venue: db.SportsVenue


@async_timer
async def send_concurrent_requests(
    hyperlinkParameters: List[Parameters], search_dates: List[date], token: str
) -> Tuple[List[UnifiedParserSchema], ...]:
    """Core logic to generate Async tasks and collect responses"""
    tasks: List[Coroutine[Any, Any, List[UnifiedParserSchema]]] = []
    parameter_sets: List[Tuple[Parameters, date]] = [
        (x, y) for x, y in itertools.product(hyperlinkParameters, search_dates)
    ]
    async with httpxAsyncClient() as client:
        for hyperlinksAndMetadata, fetch_date in parameter_sets:
            async_tasks = create_async_tasks(
                client, hyperlinksAndMetadata, fetch_date, token
            )
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
    client, hyperlinksAndMetadata: Parameters, search_date: date, token: str
) -> List[Coroutine[Any, Any, List[UnifiedParserSchema]]]:
    """Generates Async task for concurrent calls to be made later"""
    tasks: List[Coroutine[Any, Any, List[UnifiedParserSchema]]] = []
    (url, headers, payload) = (
        generate_url(hyperlinksAndMetadata, search_date),
        generate_headers(token),
        generate_payload(hyperlinksAndMetadata, search_date),
    )
    tasks.append(fetch_data(client, url, headers, metadata=hyperlinksAndMetadata))
    return tasks


def generate_headers(token: str) -> Dict:
    return {
        "Host": f"towerhamletscouncil.gladstonego.cloud",
        "Authorization": token,
        # "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    }


def generate_url(hyperlinksAndMetadata: Parameters, search_date: date) -> str:
    def format_search_date(unformatted_date: date) -> str:
        now = datetime.now()
        if search_date == now.date():
            dt = now
        else:
            dt = datetime.combine(search_date, datetime.min.time())
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    formatted_date = format_search_date(search_date)
    generated_url: str = (
        f"https://towerhamletscouncil.gladstonego.cloud/api/availability/V2/sessions?siteIds={hyperlinksAndMetadata.siteId}&activityIDs={hyperlinksAndMetadata.activityId}&webBookableOnly=true&dateFrom={formatted_date}&locationId="
    )
    logging.debug(generated_url)
    return generated_url


def generate_payload(hyperlinksAndMetadata: Parameters, search_date: date) -> dict:
    formatted_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    generated_payload: dict = {
        "siteIds": hyperlinksAndMetadata.siteId,
        "activityIDs": hyperlinksAndMetadata.activityId,
        "webBookableOnly": True,
        "dateFrom": formatted_date,
        "locationId": None,
    }
    logging.debug(generated_payload)
    return generated_payload


@async_timer
@retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
async def fetch_data(
    client, url, headers, metadata: Optional[Parameters]
) -> List[UnifiedParserSchema]:
    """Initiates request to server asynchronous using httpx"""
    logging.debug(
        f"Fetching data from {url} with headers {headers} and metadata {metadata}"
    )
    response = await client.get(url, headers=headers)
    response.raise_for_status()  # Ensure non-200 responses are treated as exceptions
    content_type = response.headers.get("content-type", "")
    raw_responses_with_schema: List[TowerHamletsResponseSchema] = (
        apply_raw_response_schema(response.json())
    )
    rolled_up_raw_responses: List[AggregatedTowerHamletsResponse] = (
        rollup_and_aggregate_data(raw_responses_with_schema)
    )
    return [
        UnifiedParserSchema.from_towerhamlets_rolledup_response(response, metadata)
        for response in rolled_up_raw_responses
    ]


def round_to_nearest_minute(time_str) -> datetime:
    """rounds str date-time to datetime python object"""
    dt = datetime.fromisoformat(time_str.rstrip("Z"))  # Remove 'Z' and parse as UTC
    if dt.second > 0:  # Round up if there are any seconds
        dt = dt.replace(second=0) + timedelta(minutes=1)
    else:
        dt = dt.replace(second=0)
    return dt


def aggregate_court_availability(data: List[Slot]) -> List[dict]:
    aggregated = defaultdict(lambda: {"available": 0})
    for entry in data:
        key = (entry.startTime, entry.endTime)
        if entry.status == "Available":
            aggregated[key]["available"] += 1

    result = [
        {"startTime": k[0], "endTime": k[1], "spaces": v["available"]}
        for k, v in aggregated.items()
    ]

    return result


def rollup_and_aggregate_data(
    results: List[TowerHamletsResponseSchema],
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
        aggregated: List[dict] = aggregate_court_availability(
            data=flattened_list_of_slots
        )
        for slot in aggregated:
            rounded_start = round_to_nearest_minute(slot.get("startTime"))
            rounded_end = round_to_nearest_minute(slot.get("endTime"))
            parsed = AggregatedTowerHamletsResponse(
                date=datetime.strptime(daily_stats.date, "%Y-%m-%d").date(),
                category=daily_stats.name,
                price="£12.80",
                starting_time=rounded_start.time(),
                ending_time=rounded_end.time(),
                spaces=slot.get("spaces"),
            )
            rolled_up_results.append(parsed)
    return rolled_up_results


def apply_raw_response_schema(api_response: dict) -> List[TowerHamletsResponseSchema]:
    try:
        aligned_api_response = [TowerHamletsResponseSchema(**x) for x in api_response]
        logging.debug(f"Data aligned with overall schema: {TowerHamletsResponseSchema}")
        return aligned_api_response
    except ValidationError as e:
        logging.error(f"Unable to apply BeWellResponseSchema to raw API json:\n{e}")
        raise ValidationError


@timeit
def get_concurrent_requests(
    hyperlinkParameters: List[Parameters], search_dates: List[date], token: str
) -> Coroutine[Any, Any, tuple[list[UnifiedParserSchema], ...]]:
    """Runs the Async API calls, collects and standardises responses and populates distance/postal metadata"""
    return send_concurrent_requests(hyperlinkParameters, search_dates, token)


def generate_parameters_set(
    hyperlinks: List[HyperlinkGenerator], venues: List[db.SportsVenue]
) -> List[Parameters]:
    # Convert list of SportsVenue to a dictionary for fast lookup
    venue_dict = {venue.slug: venue for venue in venues}
    # Create Parameters objects by matching siteId with slug
    result = [
        Parameters(
            siteId=hyper.siteId,
            activityId=hyper.activityId,
            venue=venue_dict[hyper.siteId],
        )
        for hyper in hyperlinks
        if hyper.siteId in venue_dict
    ]
    return result


def pipeline(
    search_dates: List[date], composite_identifiers: List[str]
) -> Coroutine[Any, Any, tuple[list[UnifiedParserSchema], ...]]:
    search_dates: List[date] = [
        date.today()
    ]  # Override parameter as 1 URL response contain Month's data
    sports_centre_lists: List[db.SportsVenue] = db.get_all_rows(
        db.engine,
        table=db.SportsVenue,
        expression=select(db.SportsVenue)
        .where(col(db.SportsVenue.composite_key).in_(composite_identifiers))
        .where(db.SportsVenue.organisation_website == "https://be-well.org.uk/"),
    )
    logging.info(
        f"{len(sports_centre_lists)} TowerHamlets Sports venues queried from database - fetching for: {search_dates}"
    )
    authorization_token: str = get_authorization_token()
    logging.success(
        f"Extracted Auth token for TowerHamlets website: {authorization_token}"
    )
    hyperlinkParameters: List[Parameters] = generate_parameters_set(
        siteIdsActivityIds, sports_centre_lists
    )
    return get_concurrent_requests(
        hyperlinkParameters, search_dates, token=authorization_token
    )


if __name__ == "__main__":
    logging.info("Mocking up input data (user inputs) for pipeline")
    today = date.today()
    _dates = [today + timedelta(days=i) for i in range(3)]
    sports_venues: List[db.SportsVenue] = db.get_all_rows(
        db.engine,
        db.SportsVenue,
        select(db.SportsVenue).where(db.SportsVenue.organisation == "citysport.org.uk"),
    )
    composite_identifiers: List[str] = [
        sports_venue.composite_key for sports_venue in sports_venues
    ]
    pipeline(_dates, composite_identifiers)
