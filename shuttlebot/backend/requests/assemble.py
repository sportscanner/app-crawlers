import asyncio
import itertools
import json
from datetime import date, datetime, timedelta
from typing import Dict, List
from time import time as timer

import httpx
import pandas as pd
from loguru import logger as logging

from shuttlebot import config
from shuttlebot.backend.geolocation.distance import calculate_distance_in_miles
from shuttlebot.backend.geolocation.schemas import PostcodesResponseModel
from shuttlebot.backend.organisations.better.api import generate_api_call_params
from shuttlebot.backend.requests.utils import (
    align_api_responses,
    transform_api_response,
)
from shuttlebot.backend.utils import async_timer, timeit

@async_timer
async def fetch_data(client, url, headers):
    """Initiates request to server asynchronous using httpx"""
    response = await client.get(url, headers=headers)
    content_type = response.headers.get("content-type", "")
    match response.status_code, content_type:
        case (200, "application/json"):
            json_response = response.json()
            logging.debug(f"Response for url: {url} \n{json_response}")
            return json_response
        case (_, c) if c != "application/json":
            logging.error(
                f"Response content-type is not application/json"
                f"\nResponse: {response}"
            )
            return {}
        case (_, _):
            logging.error(
                f"Request failed: status code {response.status_code}"
                f"\nResponse: {response}"
            )
            return {}


def create_async_tasks(client, parameter_sets):
    """Generates Async tasks for concurrent calls, this can be extended to add additional APIs"""
    tasks = []
    for sports_centre, fetch_date in parameter_sets:
        url, headers, _ = generate_api_call_params(
            sports_centre, fetch_date, activity="badminton-40min"
        )
        tasks.append(fetch_data(client, url, headers))
        url, headers, _ = generate_api_call_params(
            sports_centre, fetch_date, activity="badminton-60min"
        )
        tasks.append(fetch_data(client, url, headers))
    logging.info(f"Total number of concurrent request tasks: {len(tasks)}")
    return tasks


@timeit
def populate_api_response(
    sports_centre_lists: List[Dict],
    AGGREGATED_SLOTS: List[Dict],
    postcode_search: PostcodesResponseModel = None,
) -> List[Dict]:
    """Adds venue full name and postal code distance metadata to responses"""
    sports_centre_df = pd.DataFrame(sports_centre_lists).rename(
        columns={"name": "venue_name"}
    )

    def compute_postcode_distance(row) -> float:
        if postcode_search is not None:
            locationA = (row["lng"], row["lat"])
            locationB = (
                postcode_search.result.longitude,
                postcode_search.result.latitude,
            )
            distance_in_miles = calculate_distance_in_miles(locationA, locationB)
        else:
            distance_in_miles = None
        row["nearest_distance"] = distance_in_miles
        return row

    aggregated_slots_df = pd.DataFrame(AGGREGATED_SLOTS)
    logging.debug("Adding metadata from external mappings file")
    aggregated_slots_merge_metadata = sports_centre_df.merge(
        aggregated_slots_df, left_on="encoded_alias", right_on="venue_slug", how="inner"
    )
    aggregated_slots_merge_metadata = aggregated_slots_merge_metadata.apply(
        compute_postcode_distance, axis=1
    )
    aggregated_slots_enhanced_df = aggregated_slots_merge_metadata.to_json(
        orient="records"
    )
    aggregated_slots_enhanced_with_metadata = json.loads(aggregated_slots_enhanced_df)
    logging.debug(f"Post metadata addition:\n{aggregated_slots_enhanced_with_metadata}")
    return aggregated_slots_enhanced_with_metadata




@async_timer
async def send_concurrent_requests(parameter_sets):
    """Core logic to generate Async tasks and collect responses"""
    async with httpx.AsyncClient() as client:
        tasks = create_async_tasks(client, parameter_sets)
        responses = await asyncio.gather(*tasks)
    return responses


@timeit
def aggregate_and_standardise_responses(responses):
    # Process the response content
    all_fetched_slots = []
    for index, data in enumerate(responses):
        api_response = data.get("data")
        all_fetched_slots.extend(
            align_api_responses(api_response) if api_response is not None else {}
        )
    logging.debug(f"All fetched slots - standardised to same schema: \n{all_fetched_slots}")
    return all_fetched_slots


@timeit
def aggregate_api_responses(
    sports_centre_lists, dates, postcode_search: PostcodesResponseModel = None
):
    """Runs the Async API calls, collects and standardises responses and populate distance/postal metadata"""
    parameter_sets = [(x, y) for x, y in itertools.product(sports_centre_lists, dates)]
    logging.info(f"VENUES: {sports_centre_lists}")
    logging.info(f"GET RESPONSE FOR DATES: {dates}")
    responses = asyncio.run(
        send_concurrent_requests(parameter_sets)
    )
    all_fetched_slots = aggregate_and_standardise_responses(responses)
    if len(all_fetched_slots) > 0:
        metadata_enhancements_for_responses = populate_api_response(
            sports_centre_lists, all_fetched_slots, postcode_search
        )
        return metadata_enhancements_for_responses
    else:
        return []


def main():
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(3)]
    with open(f"./{config.MAPPINGS}", "r") as file:
        sports_centre_lists = json.load(file)
        aggregate_api_responses(sports_centre_lists[:2], dates)


if __name__ == "__main__":
    main()
