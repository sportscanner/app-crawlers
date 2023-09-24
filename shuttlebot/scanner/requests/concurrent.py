import asyncio
import itertools
import json

import aiohttp
from loguru import logger as logging

from shuttlebot import config
from shuttlebot.scanner.organisations.better.api import generate_api_call_params
from shuttlebot.scanner.requests.utils import parse_api_response
from shuttlebot.scanner.utils import timeit


def create_async_tasks(session, parameter_sets):
    tasks = []
    for sports_centre, date in parameter_sets:
        url, headers, _ = generate_api_call_params(sports_centre, date)
        logging.info(url)
        tasks.append(asyncio.create_task(session.get(url, headers=headers, ssl=False)))

    return tasks


async def aggregate_concurrent_api_calls(sports_centre_lists, dates):
    parameter_sets = [(x, y) for x, y in itertools.product(sports_centre_lists, dates)]
    logging.info(sports_centre_lists)
    async with aiohttp.ClientSession() as session:
        tasks = create_async_tasks(session, parameter_sets)
        responses = await asyncio.gather(*tasks)

        # Process the response content
        AGGREGATED_SLOTS = []
        for response in responses:
            # Check if the response status code is 200 (OK)
            if response.status == 200:
                # Read the response content as text
                data = await response.text()
                logging.debug(data)
                response_dict = json.loads(data)
                api_response = response_dict.get("data")
                parsed_api_response = (
                    parse_api_response(
                        api_response
                    )  # parsed JSON response to keep required columns
                    if api_response is not None
                    else {}
                )
                AGGREGATED_SLOTS.extend(parsed_api_response)
            else:
                logging.error(f"Request failed with status code {response.status}")

        logging.debug(AGGREGATED_SLOTS)
        return AGGREGATED_SLOTS


@timeit
def aggregate_api_responses(sports_centre_lists, dates):
    return asyncio.run(aggregate_concurrent_api_calls(sports_centre_lists, dates))


def main():
    dates = ["2023-09-20", "2023-09-21"]
    with open(f"./{config.MAPPINGS}", "r") as file:
        sports_centre_lists = json.load(file)
        aggregate_api_responses(sports_centre_lists, dates)


if __name__ == "__main__":
    main()
