import asyncio
import itertools
import json
from datetime import date, datetime, timedelta
from typing import Dict, List

import aiohttp
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
from shuttlebot.backend.utils import timeit


def create_async_tasks(session, parameter_sets):
    """Generates Async tasks for later concurrent call"""
    tasks = []
    for sports_centre, fetch_date in parameter_sets:
        url, headers, _ = generate_api_call_params(
            sports_centre, fetch_date, activity="badminton-40min"
        )
        tasks.append(asyncio.create_task(session.get(url, headers=headers, ssl=False)))
        url, headers, _ = generate_api_call_params(
            sports_centre, fetch_date, activity="badminton-60min"
        )
        tasks.append(asyncio.create_task(session.get(url, headers=headers, ssl=False)))

    return tasks


def populate_api_response(
    sports_centre_lists: List[Dict],
    AGGREGATED_SLOTS: List[Dict],
    postcode_search: PostcodesResponseModel = None,
) -> List[Dict]:
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


async def aggregate_concurrent_api_calls(
    sports_centre_lists, dates, postcode_search: PostcodesResponseModel = None
):
    parameter_sets = [(x, y) for x, y in itertools.product(sports_centre_lists, dates)]
    logging.info(f"VENUES: {sports_centre_lists}")
    logging.info(f"GET RESPONSE FOR DATES: {dates}")
    async with aiohttp.ClientSession() as session:
        tasks = create_async_tasks(session, parameter_sets)
        responses = await asyncio.gather(*tasks)
    # Process the response content
    all_fetched_slots = []
    for index, response in enumerate(responses):
        # Check if the response status code is 200 (OK)
        if (
            response.status == 200
            and response.headers.get("content-type") == "application/json"
        ):
            # Read the response content as text
            data = await response.text()
            logging.debug(f"Response JSON:\n{data}")
            response_dict = json.loads(data)
            api_response = response_dict.get("data")
            all_fetched_slots.extend(
                align_api_responses(api_response) if api_response is not None else {}
            )
        elif response.headers.get("content-type") != "application/json":
            logging.error(
                f"Response content-type is not application/json"
                f"\nResponse: {response}"
            )
        else:
            logging.error(
                f"Request failed: status code {response.status}"
                f"\nResponse: {response}"
            )

    aggregated_slots_enhanced_with_metadata = populate_api_response(
        sports_centre_lists, all_fetched_slots, postcode_search
    )
    return aggregated_slots_enhanced_with_metadata


@timeit
def aggregate_api_responses(
    sports_centre_lists, dates, postcode_search: PostcodesResponseModel = None
):
    """Runs the Async API calls, and collates all responses together and returns them"""
    return asyncio.run(
        aggregate_concurrent_api_calls(sports_centre_lists, dates, postcode_search)
    )


def main():
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(2)]
    with open(f"./{config.MAPPINGS}", "r") as file:
        sports_centre_lists = json.load(file)
        aggregate_api_responses(sports_centre_lists[:3], dates)


if __name__ == "__main__":
    main()
