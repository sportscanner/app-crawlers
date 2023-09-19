import itertools
import json
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests
from loguru import logger as logging

from shuttlebot import config
from shuttlebot.scanner.utils import validate_json_schema


def metadata(dates, start_time, end_time):
    logging.debug("Dates for parsing urls: " + str(dates))
    logging.debug("Time Range applied to filer slots: " + start_time + " - " + end_time)


def parse_api_request(api_response, sports_centre, date):
    AVAILABLE_SLOTS_AT_LOCATION = []
    if isinstance(api_response, dict):
        logging.debug(api_response)
        # Case 1: Single dictionary
        for _key, response_block in api_response.items():
            AVAILABLE_SLOTS_AT_LOCATION.append(
                {
                    "venue": sports_centre["name"],
                    "date": datetime.strptime(str(date), "%Y-%m-%d").date(),
                    "formatted_time": f"{response_block['starts_at']['format_24_hour']} - {response_block['ends_at']['format_24_hour']}",
                    "parsed_start_time": datetime.strptime(
                        response_block["starts_at"]["format_24_hour"], "%H:%M"
                    ).time(),
                    "parsed_end_time": datetime.strptime(
                        response_block["ends_at"]["format_24_hour"], "%H:%M"
                    ).time(),
                    "category": response_block["name"],
                    "price": "",
                    "slots_available": response_block["spaces"],
                }
            )
    else:
        if len(api_response) > 0:
            for response_block in api_response:
                AVAILABLE_SLOTS_AT_LOCATION.append(
                    {
                        "venue": sports_centre["name"],
                        "date": datetime.strptime(str(date), "%Y-%m-%d").date(),
                        "formatted_time": f"{response_block['starts_at']['format_24_hour']} - {response_block['ends_at']['format_24_hour']}",
                        "parsed_start_time": datetime.strptime(
                            response_block["starts_at"]["format_24_hour"], "%H:%M"
                        ).time(),
                        "parsed_end_time": datetime.strptime(
                            response_block["ends_at"]["format_24_hour"], "%H:%M"
                        ).time(),
                        "category": response_block["name"],
                        "price": "",
                        "slots_available": response_block["spaces"],
                    }
                )

    return AVAILABLE_SLOTS_AT_LOCATION


def api_requests_to_fetch_slots(sports_centre, date):
    url = f"https://better-admin.org.uk/api/activities/venue/{sports_centre['encoded_alias']}/activity/badminton-40min/times?date={date}"
    logging.info(f"Requests URL: {url}")
    payload = {}
    headers = {"Origin": "https://bookings.better.org.uk"}

    response = requests.request("GET", url, headers=headers, data=payload)

    response_dict = json.loads(response.text)
    logging.debug(
        f'"sports-centre": {sports_centre} - date: {date} - response: {response_dict}'
    )

    return response_dict["data"]


def apply_slots_preference_filter(
    ALL_AVAILABLE_SLOTS, start_time_preference, end_time_preference
):
    preferred_slots = []
    start_time_range = datetime.strptime(start_time_preference, "%H:%M").time()
    end_time_range = datetime.strptime(end_time_preference, "%H:%M").time()
    for slot in ALL_AVAILABLE_SLOTS:
        if (
            slot["parsed_start_time"] >= start_time_range
            and slot["parsed_end_time"] <= end_time_range
            and int(slot["slots_available"]) > 0
        ):
            preferred_slots.append(slot)
        else:
            pass
    logging.info(preferred_slots)
    return preferred_slots


def filter_and_transform_to_dataframe(ALL_AVAILABLE_SLOTS, start_time, end_time):
    # Combine the results from all the executions
    filtered_results = apply_slots_preference_filter(
        ALL_AVAILABLE_SLOTS,
        start_time_preference=start_time,
        end_time_preference=end_time,
    )

    try:
        if not filtered_results:
            raise ValueError("filtered_results is empty")

        _to_dataframe = (
            pd.DataFrame(filtered_results)
            .sort_values(by=["date", "parsed_start_time"], ascending=True)
            .drop(
                columns=["parsed_start_time", "parsed_end_time", "category", "price"],
                axis=1,
            )
        )

        # Chain the transformations to format the 'date' column
        _to_dataframe["date"] = pd.to_datetime(_to_dataframe["date"]).dt.strftime(
            "%Y-%m-%d (%A)"
        )

    except ValueError:
        # Handle the case where filtered_results is an empty list
        logging.warning("No slots available after applying selected filters")
        _to_dataframe = (
            pd.DataFrame()
        )  # Create an empty DataFrame or take alternative actions

    return _to_dataframe.reset_index(drop=True)


def slots_scanner(dates, start_time, end_time):
    # GLOBAL: Read the JSON file
    with open(f"./{config.MAPPINGS}", "r") as file:
        sports_centre_lists = json.load(file)
        if validate_json_schema(sports_centre_lists):
            parameter_sets = [
                (x, y) for x, y in itertools.product(sports_centre_lists, dates)
            ]
            logging.info(sports_centre_lists)

            # Start the timer
            process_start_time = time.time()

            ALL_AVAILABLE_SLOTS = []
            for sports_centre, date in parameter_sets:
                api_response = api_requests_to_fetch_slots(sports_centre, date)
                AVAILABLE_SLOTS_AT_LOCATION = parse_api_request(
                    api_response, sports_centre, date
                )
                ALL_AVAILABLE_SLOTS.extend(AVAILABLE_SLOTS_AT_LOCATION)

            logging.debug(f"ALL_AVAILABLE_SLOTS: {ALL_AVAILABLE_SLOTS}")

            # Stop the timer
            process_end_time = time.time()

            # Calculate the elapsed time
            elapsed_time = process_end_time - process_start_time
            # Print the elapsed time
            logging.debug(f"Elapsed fetch time: {elapsed_time} seconds")

            slots_dataframe = filter_and_transform_to_dataframe(
                ALL_AVAILABLE_SLOTS, start_time, end_time
            )
            return slots_dataframe


def main():
    today = date.today()
    raw_dates = [today + timedelta(days=i) for i in range(2)]
    dates = [date.strftime("%Y-%m-%d") for date in raw_dates]
    start_time, end_time = config.START_TIME, config.END_TIME

    metadata(dates, start_time, end_time)
    slots_scanner(dates, start_time, end_time)


if __name__ == "__main__":
    main()
