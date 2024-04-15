import itertools
import json
from datetime import date, datetime, timedelta

import pandas as pd
from loguru import logger as logging

from shuttlebot import config
from shuttlebot.backend.geolocation.schemas import PostcodesResponseModel
from shuttlebot.backend.pipeline import aggregate_api_responses
from shuttlebot.backend.compilation.utils import transform_api_response
from shuttlebot.backend.utils import (
    find_consecutive_slots,
    timeit,
    validate_json_schema,
)


def metadata(dates, start_time, end_time):
    logging.info("Dates for parsing urls: " + str(dates))
    logging.info("Time Range applied to filer slots: " + start_time + " - " + end_time)


def apply_slots_preference_filter(
    AGGREGATED_SLOTS, start_time_preference, end_time_preference
):
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
    logging.debug(f"Available timebound slots:\n{available_timebound_slots}")
    logging.success(
        f"Available slots after filtering: {len(available_timebound_slots)}"
    )

    return available_timebound_slots


def dataframe_display_transformations(available_slots_with_preferences):
    transformed_dataframe = (
        pd.DataFrame(available_slots_with_preferences)
        .sort_values(by=["date", "parsed_start_time"], ascending=True)[
            ["date", "formatted_time", "name"]
        ]  # selecting columns in pandas
        .rename(
            columns={"formatted_time": "Slot time", "name": "Venue", "date": "Date"}
        )
    )

    # Chain the transformations to format the 'date' column
    transformed_dataframe["Date"] = pd.to_datetime(
        transformed_dataframe["Date"]
    ).dt.strftime("%Y-%m-%d (%A)")

    return transformed_dataframe


def filter_and_transform_to_dataframe(
    available_slots_with_preferences, start_time, end_time
):
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


def trim_api_response_fields(
    aggregated_slots_enhanced_with_metadata: list[dict],
) -> list[dict]:
    aggregated_slots_parsed = [
        transform_api_response(response)
        for response in aggregated_slots_enhanced_with_metadata
    ]
    logging.debug(aggregated_slots_parsed)
    return aggregated_slots_parsed


def slots_scanner(
    sports_centre_lists,
    dates,
    start_time,
    end_time,
    postcode_search: PostcodesResponseModel = None,
):
    aggregated_slots_enhanced_with_metadata = aggregate_api_responses(
        sports_centre_lists, dates, postcode_search
    )
    trimmed_api_response_fields = trim_api_response_fields(
        aggregated_slots_enhanced_with_metadata
    )
    available_slots_with_preferences = apply_slots_preference_filter(
        trimmed_api_response_fields,
        start_time_preference=start_time,
        end_time_preference=end_time,
    )
    slots_dataframe = filter_and_transform_to_dataframe(
        available_slots_with_preferences, start_time, end_time
    )
    return slots_dataframe, available_slots_with_preferences


def main():
    today = date.today()
    raw_dates = [today + timedelta(days=i) for i in range(2)]
    dates = [date.strftime("%Y-%m-%d") for date in raw_dates]
    start_time, end_time = config.START_TIME, config.END_TIME

    metadata(dates, start_time, end_time)
    slots_scanner(get_mappings(), dates, start_time, end_time)


if __name__ == "__main__":
    main()
