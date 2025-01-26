import json
from typing import Optional

import requests
from loguru import logger as logging

from sportscanner.api.routers.geolocation.schemas import PostcodesResponseModel
from sportscanner.utils import timeit


def validate_response(response):
    if response.status_code == 200:
        response_dict = json.loads(response.text)
        logging.debug(f"API Response:\n{response_dict}\n")
        return response_dict
    else:
        logging.error(f"Request failed with status code {response.status_code}")
        return None


@timeit
def get_postcode_metadata(postcode: str) -> Optional[PostcodesResponseModel]:
    url = f"https://api.postcodes.io/postcodes/" f"{postcode}"
    headers, payload = {}, {}
    logging.info(f"Requests URL: {url}")

    response = requests.request("GET", url, headers=headers, data=payload)
    validated_response = validate_response(response)
    return (
        PostcodesResponseModel(**validated_response)
        if validated_response is not None
        else None
    )


def postcode_autocompletion(search_term: str, limit: int = 5):
    url = f"https://api.postcodes.io/postcodes/" f"{search_term}/autocomplete"
    headers, payload = {}, {}
    response = requests.request("GET", url, headers=headers, data=payload)
    validated_response = validate_response(response)
    return (
        validated_response["result"][:limit]
        if validated_response.get("result") is not None
        else []
    )


@timeit
def validate_uk_postcode(postcode: str) -> bool:
    url = f"https://api.postcodes.io/postcodes/" f"{postcode}/validate"

    headers, payload = {}, {}
    logging.info(f"Requests URL: {url}")

    response = requests.request("GET", url, headers=headers, data=payload)
    return True if validate_response(response).get("result", "") is True else False


if __name__ == "__main__":
    logging.info(
        "Running script standalone with testdata for London bridge postcode: SE1 9BG"
    )
    logging.info(validate_uk_postcode("SE1 9BG"))
    logging.success(get_postcode_metadata("SE1 9BG"))
    logging.success(get_postcode_metadata("SE29qq"))
