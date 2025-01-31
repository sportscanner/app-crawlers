import asyncio
import itertools
from datetime import date, timedelta
from typing import Any, Coroutine, Dict, List, Tuple

import httpx
from loguru import logger as logging
from lxml.html.diff import token
from prefect.cache_policies import NO_CACHE
from pydantic import ValidationError
from sqlmodel import col, select
from streamlit import rerun
from tenacity import retry

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.helpers import SportscannerCrawlerBot
from sportscanner.crawlers.parsers.towerhamlets.Authenticate import get_authorization_token
from sportscanner.crawlers.anonymize.proxies import httpxAsyncClient
from sportscanner.crawlers.parsers.citysports.schema import CitySportsResponseSchema
from sportscanner.crawlers.parsers.schema import UnifiedParserSchema
from sportscanner.crawlers.parsers.towerhamlets.mappings import parameter_sets, HyperlinkGenerator
from sportscanner.utils import async_timer, timeit
from sportscanner.crawlers.parsers.towerhamlets.schemas import Activity
from prefect import flow, task


@task(cache_policy=NO_CACHE)
@async_timer
async def send_concurrent_requests(
    hyperlinkParamsMappings: List[HyperlinkGenerator],
    search_dates: List,
    token: str
) -> Tuple[List[UnifiedParserSchema], ...]:
    """Core logic to generate Async tasks and collect responses"""
    tasks: List[Coroutine[Any, Any, List[UnifiedParserSchema]]] = []
    parameter_sets: List[Tuple[db.SportsVenue, date]] = [
        (x, y) for x, y in itertools.product(hyperlinkParamsMappings, search_dates)
    ]
    async with httpxAsyncClient() as client:
        for hyperLinkParams, fetch_date in parameter_sets:
            async_tasks = create_async_tasks(client, hyperLinkParams, fetch_date, token)
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


@task(cache_policy=NO_CACHE)
def create_async_tasks(
    client, hyperLinkParams: HyperlinkGenerator, search_date: date, token: str
) -> List[Coroutine[Any, Any, List[UnifiedParserSchema]]]:
    """Generates Async task for concurrent calls to be made later"""
    tasks: List[Coroutine[Any, Any, List[UnifiedParserSchema]]] = []
    url, headers = generate_url(hyperLinkParams, search_date), generate_headers(token)
    tasks.append(fetch_data(client, url, headers, metadata=None))
    return tasks


def generate_headers(token: str) -> Dict:
    return {
        "Host": f"towerhamletscouncil.gladstonego.cloud",
        "Authorization": token
        # "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    }

def generate_url(hyperLinkParams: HyperlinkGenerator, search_date: date) -> str:
    formatted_date = search_date.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    generated_url: str = (
        f"https://towerhamletscouncil.gladstonego.cloud/api/availability/V2/sessions?siteIds={hyperLinkParams.siteId}&activityIDs={hyperLinkParams.activityId}&webBookableOnly=true&dateFrom={formatted_date}&locationId="
    )
    logging.debug(generated_url)
    return generated_url


@task(cache_policy=NO_CACHE)
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
            return [Activity(**x) for x in json_response]
            # raw_responses_with_schema = apply_raw_response_schema(response.json())
            # return [
            #     UnifiedParserSchema.from_citysports_api_response(response, metadata)
            #     for response in raw_responses_with_schema
            #     if response.ActivityGroupDescription == "Badminton"
            # ]
        case _:
            logging.error(
                f"Response status code is not: Response [200 OK]"
                f"\nResponse: {response}"
            )
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


@task
@async_timer
async def get_concurrent_requests(
        hyperlinkParamsMappings: List[HyperlinkGenerator], search_dates: List, token: str
) -> Tuple[List[UnifiedParserSchema], ...]:
    """Runs the Async API calls, collects and standardises responses and populates distance/postal metadata"""

    responses_from_all_sources = await SportscannerCrawlerBot(  # ✅ Directly await the async function
        send_concurrent_requests(hyperlinkParamsMappings, search_dates, token)
    )
    return responses_from_all_sources

@task()
async def pipeline(search_dates: List[date]) -> Tuple[List[UnifiedParserSchema], ...]:
    """Prefect Flow"""

    authorization_token = await get_authorization_token()  # ✅ Await the async function
    logging.success(authorization_token)

    outputs = await get_concurrent_requests(parameter_sets, search_dates, token=authorization_token)
    return outputs

@task()
def main():
    logging.info("Mocking up input data (user inputs) for pipeline")
    today = date.today()
    _dates = [today + timedelta(days=i) for i in range(1)]

    asyncio.run(pipeline(_dates))  # ✅ Use `asyncio.run()`
    return []

@task()
def hello(output):
    return []

@task()
def hello1(xx):
    return True

@flow()
def endtoend():
    output = main()
    hello_print = hello(output)
    hello1print = hello1(hello_print)
    return hello1print

if __name__ == "__main__":
    endtoend()

