import itertools
import json
from datetime import date, datetime, timedelta

import pandas as pd
from loguru import logger as logging

from shuttlebot import config
from shuttlebot.scanner.requests.concurrent import aggregate_api_responses
from shuttlebot.scanner.utils import timeit, validate_json_schema


def metadata(dates, start_time, end_time):
    """Logs initial search parameters specified in the search query"""
    logging.info("Dates for parsing urls: " + str(dates))
    logging.info("Time Range applied to filer slots: " + start_time + " - " + end_time)


def apply_slots_preference_filter(
    AGGREGATED_SLOTS, start_time_preference, end_time_preference
):
    """Returns available slots during the defined start and end time"""
    available_timebound_slots = []
    start_time_range = datetime.strptime(start_time_preference, "%H:%M").time()
    end_time_range = datetime.strptime(end_time_preference, "%H:%M").time()
    for slot in AGGREGATED_SLOTS:
        if (
            slot["parsed_start_time"] >= start_time_range
            and slot["parsed_end_time"] <= end_time_range
            and int(slot["slots_available"]) > 0
        ):
            available_timebound_slots.append(slot)
        else:
            pass
    logging.debug(available_timebound_slots)
    logging.success(
        f"Available slots after filtering: {len(available_timebound_slots)}"
    )
    return available_timebound_slots


def dataframe_display_transformations(available_slots_with_preferences):
    """Converting List of dict into a pandas dataframe for display purpose"""
    transformed_dataframe = (
        pd.DataFrame(available_slots_with_preferences)
        .sort_values(by=["date", "parsed_start_time"], ascending=True)
        .drop(
            columns=["parsed_start_time", "parsed_end_time", "category", "price"],
            axis=1,
        )
    )

    # Chain the transformations to format the 'date' column
    transformed_dataframe["date"] = pd.to_datetime(
        transformed_dataframe["date"]
    ).dt.strftime("%Y-%m-%d (%A)")

    return transformed_dataframe


def filter_and_transform_to_dataframe(AGGREGATED_SLOTS, start_time, end_time):
    # Combine the results from all the executions
    available_slots_with_preferences = apply_slots_preference_filter(
        AGGREGATED_SLOTS,
        start_time_preference=start_time,
        end_time_preference=end_time,
    )

    try:
        if not available_slots_with_preferences:
            raise ValueError("Available slots - with preferences filter, is empty")

        transformed_dataframe = dataframe_display_transformations(
            available_slots_with_preferences
        )  # keeps required columns and field formattings

    except ValueError:
        # Handle the case where filtered_results is an empty list
        logging.warning("No slots available after applying selected filters")
        transformed_dataframe = (
            pd.DataFrame()
        )  # Create an empty DataFrame or take alternative actions

    return transformed_dataframe.reset_index(drop=True)


def slots_scanner(sports_centre_lists, dates, start_time, end_time):
    AGGREGATED_SLOTS = aggregate_api_responses(sports_centre_lists, dates)
    slots_dataframe = filter_and_transform_to_dataframe(
        AGGREGATED_SLOTS, start_time, end_time
    )
    return slots_dataframe


def get_mappings():
    """Fetches the sports centres names and slug/alias from mappings file"""
    with open(f"./{config.MAPPINGS}", "r") as file:
        sports_centre_lists = json.load(file)
        if validate_json_schema(sports_centre_lists):
            return sports_centre_lists
        else:
            logging.error("JSON schema is invalid for mappings")
            return None


def main():
    today = date.today()
    raw_dates = [today + timedelta(days=i) for i in range(2)]
    dates = [date.strftime("%Y-%m-%d") for date in raw_dates]
    start_time, end_time = config.START_TIME, config.END_TIME

    metadata(dates, start_time, end_time)
    slots_scanner(get_mappings(), dates, start_time, end_time)


if __name__ == "__main__":
    main()
