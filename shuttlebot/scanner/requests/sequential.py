import itertools
import json

import requests
from loguru import logger as logging

from shuttlebot.scanner.organisations.better.api import generate_api_call_params
from shuttlebot.scanner.requests.utils import parse_api_response
from shuttlebot.scanner.utils import timeit


@timeit
def make_sequential_api_calls(sports_centre, date):
    url, headers, payload = generate_api_call_params(sports_centre, date)
    logging.info(f"Requests URL: {url}")

    response = requests.request("GET", url, headers=headers, data=payload)
    if response.status_code == 200:
        response_dict = json.loads(response.text)
        logging.debug(f"API Response:\n{response_dict}\n")
        return response_dict.get("data")
    else:
        logging.error(f"Request failed with status code {response.status_code}")
        return None


@timeit
def aggregate_api_responses(sports_centre_lists, dates):
    parameter_sets = [(x, y) for x, y in itertools.product(sports_centre_lists, dates)]
    logging.info(sports_centre_lists)

    AGGREGATED_SLOTS = []
    for sports_centre, date in parameter_sets:
        api_response = make_sequential_api_calls(
            sports_centre, date
        )  # API call to get slots for centre
        parsed_api_response = (
            parse_api_response(
                api_response
            )  # parsed JSON response to keep required columns
            if api_response is not None
            else {}
        )
        AGGREGATED_SLOTS.extend(parsed_api_response)
    logging.debug(AGGREGATED_SLOTS)
    return AGGREGATED_SLOTS
