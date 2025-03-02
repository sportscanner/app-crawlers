from datetime import date, timedelta
from typing import List

from loguru import logger as logging


import logging

def validate_api_response(response, content_type: str, url: str):
    """Validating API response based on the status codes and content type"""
    if response.status_code == 200 and "application/json" in content_type:
        json_response = response.json()
        logging.debug(f"Raw response for url: {url} \n{json_response}")
        return json_response
    elif "application/json" not in content_type:
        logging.error(
            f"Response content-type does not contain 'application/json'"
            f"\nURL: {url}"
            f"\nResponse: {response}"
        )
        return {}
    else:
        logging.error(
            f"Request failed: status code {response.status_code}"
            f"\nURL: {url}"
            f"\nResponse: {response}"
        )
        return {}

from datetime import date


def formatted_date_list(search_dates: List[date]):
    return [x.strftime("%Y-%m-%d") for x in search_dates]
