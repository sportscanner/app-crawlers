import asyncio
import itertools
import json
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import httpx
from loguru import logger as logging
from pydantic import BaseModel, ValidationError
from sqlmodel import Session, col, select

import shuttlebot.backend.database as db
from shuttlebot import config
from shuttlebot.backend.parsers.better.schema import BetterApiResponseSchema
from shuttlebot.backend.parsers.schema import UnifiedParserSchema
from shuttlebot.backend.parsers.utils import validate_api_response
from shuttlebot.backend.utils import async_timer, timeit
from shuttlebot.config import SportsCentre


@async_timer
async def send_concurrent_requests(parameter_sets: List[Tuple[SportsCentre, date]]):
    """Core logic to generate Async tasks and collect responses"""
    tasks = []
    async with httpx.AsyncClient(
        limits=httpx.Limits(max_connections=250, max_keepalive_connections=20),
        timeout=httpx.Timeout(timeout=15.0),
    ) as client:
        for sports_centre, fetch_date in parameter_sets:
            async_tasks = create_async_tasks(client, sports_centre, fetch_date)
            tasks.extend(async_tasks)
        logging.info(f"Total number of concurrent request tasks: {len(tasks)}")
        responses = await asyncio.gather(*tasks)
    return responses


def create_async_tasks(client, sports_centre: SportsCentre, fetch_date: date):
    """Generates Async task for concurrent calls to be made later"""
    tasks = []
    for activity_duration in ["badminton-40min", "badminton-60min"]:
        url, headers, _ = generate_api_call_params(
            sports_centre, fetch_date, activity=activity_duration
        )
        tasks.append(fetch_data(client, url, headers))
    return tasks


def generate_api_call_params(
    sports_centre: SportsCentre, fetch_date: date, activity: str
):
    """Generates URL, Headers and Payload information for the API curl request"""
    url = (
        f"https://better-admin.org.uk/api/activities/venue/"
        f"{sports_centre.slug}/activity/{activity}/times?date={fetch_date}"
    )
    logging.debug(url)
    headers = {
        "origin": "https://bookings.better.org.uk",
        "referer": f"https://bookings.better.org.uk/location/{sports_centre.slug}"
        f"/{activity}",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    }
    payload: Dict = {}
    return url, headers, payload


@async_timer
async def fetch_data(client, url, headers):
    """Initiates request to server asynchronous using httpx"""
    response = await client.get(url, headers=headers)
    content_type = response.headers.get("content-type", "")
    validated_response = validate_api_response(response, content_type, url)
    validated_response_data = validated_response.get("data")
    if validated_response_data is not None:
        raw_responses_with_schema = apply_raw_response_schema(validated_response_data)
        return [
            UnifiedParserSchema.from_better_api_response(response)
            for response in raw_responses_with_schema
        ]
    else:
        return {}


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
                    f"Unable to apply Better API response schema to raw API json:\n{e}"
                )
    logging.debug(f"Data aligned with overall schema: {BetterApiResponseSchema}")
    return aligned_api_response


@timeit
def fetch_data_across_centres(
    sports_centre_lists: List[SportsCentre], dates: List[date]
) -> List[UnifiedParserSchema]:
    """Runs the Async API calls, collects and standardises responses and populate distance/postal
    metadata"""
    parameter_sets: List[Tuple[SportsCentre, date]] = [
        (x, y) for x, y in itertools.product(sports_centre_lists, dates)
    ]
    logging.debug(
        f"VENUES: {[sports_centre.venue_name for sports_centre in sports_centre_lists]}"
    )
    responses_from_all_sources: List[List[UnifiedParserSchema]] = asyncio.run(
        send_concurrent_requests(parameter_sets)
    )
    all_fetched_slots: List[UnifiedParserSchema] = [
        item for sublist in responses_from_all_sources for item in sublist
    ]
    logging.debug(f"Unified parser schema mapped responses:\n{all_fetched_slots}")
    return all_fetched_slots


def pipeline(dates: List[date]) -> List[UnifiedParserSchema]:
    sports_centre_lists = db.get_all_rows(
        db.engine,
        table=db.SportsVenue,
        expression=select(db.SportsVenue).where(
            db.SportsVenue.organisation_name == "better.org.uk"
        ),
    )
    logging.success(
        f"{len(sports_centre_lists)} Sports venue data queried from database"
    )
    return fetch_data_across_centres(sports_centre_lists, dates)


if __name__ == "__main__":
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(6)]
    sports_venues: List[db.SportsVenue] = db.get_all_rows(
        db.engine, db.SportsVenue, select(db.SportsVenue)
    )
    sports_venues_slugs = [sports_venue.slug for sports_venue in sports_venues]
    pipeline(dates, sports_venues_slugs[:3])
