import asyncio
from datetime import date, timedelta
from typing import List, Dict, Coroutine, Any, Tuple

import httpx
from loguru import logger as logging
from pydantic import ValidationError
from sqlmodel import select, col

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.citysports.schema import CitySportsResponseSchema
from sportscanner.crawlers.parsers.schema import UnifiedParserSchema
from sportscanner.utils import async_timer, timeit
from rich import print
from sportscanner.crawlers.anonymize.proxies import httpxAsyncClient


@async_timer
async def send_concurrent_requests(search_dates: List[date]) -> Tuple[List[UnifiedParserSchema], ...]:
    """Core logic to generate Async tasks and collect responses"""
    tasks = []
    async with httpxAsyncClient() as client:
        for search_date in search_dates:
            async_tasks = create_async_tasks(client, search_date)
            tasks.extend(async_tasks)
        logging.info(f"Total number of concurrent request tasks: {len(tasks)}")
        responses = await asyncio.gather(*tasks)
    return responses


def create_async_tasks(client, search_date: date) -> List[Coroutine[Any, Any, List[UnifiedParserSchema]]]:
    """Generates Async task for concurrent calls to be made later"""
    tasks: List[Coroutine[Any, Any, List[UnifiedParserSchema]]] = []
    url, headers, _ = generate_api_call_params(search_date)
    tasks.append(fetch_data(client, url, headers))
    return tasks


def generate_api_call_params(search_date: date):
    formatted_search_date = search_date.strftime("%Y/%m/%d")
    """Generates URL, Headers and Payload information for the API curl request"""
    url = (
        f"https://ipinfo.io?token=a434c9a79cf3c2"
    )
    logging.debug(url)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    }
    payload: Dict = {}
    return url, headers, payload


@async_timer
async def fetch_data(client, url, headers)-> List[UnifiedParserSchema]:
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
    return response.json()


def apply_raw_response_schema(api_response) -> List[CitySportsResponseSchema]:
    try:
        aligned_api_response = [
            CitySportsResponseSchema(**response_block)
            for response_block in api_response
        ]
        logging.debug(f"Data aligned with overall schema: {CitySportsResponseSchema}")
        return aligned_api_response
    except ValidationError as e:
        logging.error(
            f"Unable to apply CitySportsResponseSchema to raw API json:\n{e}"
        )
        raise ValidationError


@timeit
def get_concurrent_requests(search_dates: List) -> Coroutine[Any, Any, tuple[list[UnifiedParserSchema], ...]]:
    """Runs the Async API calls, collects and standardises responses and populate distance/postal
    metadata"""
    return send_concurrent_requests(search_dates)


def pipeline(search_dates: List[date], venue_slugs: List[str]) -> Coroutine[Any, Any, tuple[list[UnifiedParserSchema], ...]]:
    return get_concurrent_requests(search_dates)


if __name__ == "__main__":
    logging.info("Mocking up input data (user inputs) for pipeline")
    today = date.today()
    _dates = [today + timedelta(days=i) for i in range(3)]
    sports_venues: List[db.SportsVenue] = db.get_all_rows(
        db.engine, db.SportsVenue,
        select(db.SportsVenue)
        .where(db.SportsVenue.organisation == "citysport.org.uk")
    )
    venues_slugs = [sports_venue.slug for sports_venue in sports_venues]
    pipeline(_dates, venues_slugs[:4])
