import json

import requests
from loguru import logger as logging


def generate_api_call_params(sports_centre, date, activity="badminton-40min"):
    """Generates URL, Headers and Payload information for the API curl request"""
    url = (
        f"https://better-admin.org.uk/api/activities/venue/"
        f"{sports_centre['encoded_alias']}/activity/{activity}/times?date={date}"
    )
    logging.debug(url)
    headers = {
        "Origin": "https://bookings.better.org.uk",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    }
    payload = {}
    return url, headers, payload


def get_slots(sports_centre, date):
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
