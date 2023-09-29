import asyncio
import itertools
import json
from datetime import date, datetime, timedelta

import aiohttp
import pandas as pd
from loguru import logger as logging

from shuttlebot import config
from shuttlebot.scanner.organisations.better.api import generate_api_call_params
from shuttlebot.scanner.requests.utils import align_api_responses, parse_api_response
from shuttlebot.scanner.utils import timeit


def create_async_tasks(session, parameter_sets):
    tasks = []
    for sports_centre, date in parameter_sets:
        url, headers, _ = generate_api_call_params(sports_centre, date)
        logging.debug(url)
        tasks.append(asyncio.create_task(session.get(url, headers=headers, ssl=False)))

    return tasks


def populate_api_response(sports_centre_lists, AGGREGATED_SLOTS):
    sports_centre_df = pd.DataFrame(sports_centre_lists).rename(
        columns={"name": "venue_name"}
    )
    aggregated_slots_df = pd.DataFrame(AGGREGATED_SLOTS)
    aggregated_slots_enhanced_df = sports_centre_df.merge(
        aggregated_slots_df, left_on="encoded_alias", right_on="venue_slug", how="inner"
    ).to_json(orient="records")
    aggregated_slots_enhanced = json.loads(aggregated_slots_enhanced_df)
    aggregated_slots_parsed = [
        parse_api_response(response) for response in aggregated_slots_enhanced
    ]
    logging.debug(aggregated_slots_parsed)
    return aggregated_slots_parsed


async def aggregate_concurrent_api_calls(sports_centre_lists, dates):
    parameter_sets = [(x, y) for x, y in itertools.product(sports_centre_lists, dates)]
    logging.info(f"VENUES: {sports_centre_lists}")
    logging.info(f"GET RESPONSE FOR DATES: {dates}")
    async with aiohttp.ClientSession() as session:
        tasks = create_async_tasks(session, parameter_sets)
        responses = await asyncio.gather(*tasks)

        # Process the response content
        AGGREGATED_SLOTS = []
        for response in responses:
            # Check if the response status code is 200 (OK)
            if (
                response.status == 200
                and response.headers.get("content-type") == "application/json"
            ):
                # Read the response content as text
                data = await response.text()
                logging.debug(data)
                response_dict = json.loads(data)
                api_response = response_dict.get("data")
                AGGREGATED_SLOTS.extend(
                    align_api_responses(api_response)
                    if api_response is not None
                    else {}
                )
            elif response.headers.get("content-type") != "application/json":
                logging.error(
                    f"Response content-type is not application/json \n Response: {response}"
                )
            else:
                logging.error(
                    f"Request failed: status code {response.status} \n Response: {response}"
                )

        aggregated_slots_parsed = populate_api_response(
            sports_centre_lists, AGGREGATED_SLOTS
        )
        return aggregated_slots_parsed


@timeit
def aggregate_api_responses(sports_centre_lists, dates):
    return asyncio.run(aggregate_concurrent_api_calls(sports_centre_lists, dates))


def main():
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(2)]
    with open(f"./{config.MAPPINGS}", "r") as file:
        sports_centre_lists = json.load(file)
        aggregate_api_responses(sports_centre_lists[:3], dates)


if __name__ == "__main__":
    main()
