from datetime import date, timedelta, datetime

from loguru import logger as logging
from typing import List, Optional, Dict
import json
import itertools
import asyncio
import httpx
from shuttlebot.backend.parsers.schema import UnifiedParserSchema
from shuttlebot.backend.parsers.utils import validate_api_response
from shuttlebot.backend.utils import async_timer, timeit
from shuttlebot.config import SportsCentre
from shuttlebot import config
from shuttlebot.backend.parsers.citysports.schema import CitySportsResponseSchema
import shuttlebot.backend.database as db
from sqlmodel import Session, select

from pydantic import BaseModel, ValidationError


@async_timer
async def send_concurrent_requests(search_dates: List[date]):
    """Core logic to generate Async tasks and collect responses"""
    tasks = []
    async with httpx.AsyncClient(
            limits=httpx.Limits(max_connections=250, max_keepalive_connections=20),
            timeout=httpx.Timeout(timeout=15.0)
    ) as client:
        for search_date in search_dates:
            async_tasks = create_async_tasks(client, search_date)
            tasks.extend(async_tasks)
        logging.info(f"Total number of concurrent request tasks: {len(tasks)}")
        responses = await asyncio.gather(*tasks)
    return responses


def create_async_tasks(client, search_date: date):
    """Generates Async task for concurrent calls to be made later"""
    tasks = []
    url, headers, _ = generate_api_call_params(search_date)
    tasks.append(fetch_data(client, url, headers))
    return tasks


def generate_api_call_params(search_date: date):
    formatted_search_date = search_date.strftime("%Y/%m/%d")
    """Generates URL, Headers and Payload information for the API curl request"""
    # https://bookings.citysport.org.uk/LhWeb/en/api/Sites/1/Timetables/ActivityBookings?date=2024/04/26&pid=0
    url = (
        f"https://bookings.citysport.org.uk/LhWeb/en/api/Sites/1/Timetables/ActivityBookings"
        f"?date={formatted_search_date}&pid=0"
    )
    logging.debug(url)
    headers = {
        "Referer": "https://bookings.citysport.org.uk/LhWeb/en/Public/Bookings",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    }
    payload: Dict = {}
    return url, headers, payload


@async_timer
async def fetch_data(client, url, headers):
    """Initiates request to server asynchronous using httpx"""
    response = await client.get(url, headers=headers)
    content_type = response.headers.get("content-type", "")
    match response.status_code:
        case (200):
            json_response = response.json()
            logging.debug(f"Request success: Raw response for url: {url} \n{json_response}")
        case (_):
            logging.error(
                f"Response status code is not: Response [200 OK]"
                f"\nResponse: {response}"
            )

    if len(response.json()) > 0:
        raw_responses_with_schema = apply_raw_response_schema(
            response.json()
        )
        return [UnifiedParserSchema.from_citysports_api_response(response) for response in
                raw_responses_with_schema]
    else:
        return []


def apply_raw_response_schema(api_response) -> List[CitySportsResponseSchema]:
    try:
        aligned_api_response = [CitySportsResponseSchema(**response_block) for response_block in api_response]
        logging.debug(f"Data aligned with overall schema: {CitySportsResponseSchema}")
        return aligned_api_response
    except ValidationError as e:
        logging.error(f"Unable to apply Better API response schema to raw API json:\n{e}")
        raise ValidationError


@timeit
def fetch_data_at_venue(search_dates: List) -> List[UnifiedParserSchema]:
    """Runs the Async API calls, collects and standardises responses and populate distance/postal
    metadata"""
    responses_from_all_sources: List[List[UnifiedParserSchema]] = asyncio.run(
        send_concurrent_requests(search_dates)
    )
    all_fetched_slots: List[UnifiedParserSchema] = [item for sublist in
                                                    responses_from_all_sources for item in sublist]
    logging.debug(f"Unified parser schema mapped responses:\n{all_fetched_slots}")
    return all_fetched_slots


def pipeline(search_dates: List) -> List[UnifiedParserSchema]:
    sports_centre_lists = db.get_all_rows(
        db.engine, table=db.SportsVenue,
        expression=select(db.SportsVenue).where(db.SportsVenue.organisation_name == "citysport.org.uk")
    )
    logging.success("Sports venue data loaded from database")
    return fetch_data_at_venue(search_dates)


if __name__ == "__main__":
    today = date.today()
    search_dates = [today + timedelta(days=i) for i in range(2)]
    pipeline(search_dates)
