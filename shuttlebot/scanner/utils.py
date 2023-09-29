import itertools
import sys
from datetime import date, datetime, time
from time import time as timer

import jsonschema
import pandas as pd
from loguru import logger as logging

from shuttlebot import config

pd.set_option("display.max_columns", None)


def validate_json_schema(data):
    try:
        # Validate the data against the schema
        jsonschema.validate(data, config.schema)
        logging.success("JSON data is valid according to the schema")
        return True
    except jsonschema.exceptions.ValidationError as e:
        logging.error("JSON data is not valid according to the schema:")
        logging.error(e)
        return False


def timeit(func):
    # This function shows the execution time of
    # the function object passed
    def wrap_func(*args, **kwargs):
        tic = timer()
        result = func(*args, **kwargs)
        tac = timer()
        logging.info(f"Function {func.__name__!r} executed in {(tac - tic):.4f}s")
        return result

    return wrap_func


##################################

data_list = [
    {
        "venue": "swiss-cottage-leisure-centre",
        "date": date(2023, 9, 26),
        "parsed_start_time": time(18, 0),
        "parsed_end_time": time(18, 40),
    },
    {
        "venue": "swiss-cottage-leisure-centre",
        "date": date(2023, 9, 26),
        "parsed_start_time": time(18, 40),
        "parsed_end_time": time(19, 20),
    },
    {
        "venue": "swiss-cottage-leisure-centre",
        "date": date(2023, 9, 26),
        "parsed_start_time": time(19, 20),
        "parsed_end_time": time(20, 0),
    },
    {
        "venue": "swiss-cottage-leisure-centre",
        "date": date(2023, 9, 26),
        "parsed_start_time": time(20, 15),
        "parsed_end_time": time(20, 45),
    },
    {
        "venue": "swiss-cottage-leisure-centre",
        "date": date(2023, 9, 26),
        "parsed_start_time": time(20, 45),
        "parsed_end_time": time(21, 15),
    },
]


@timeit
def find_consecutive_slots(
    sports_centre_lists: list, dates: list, slots: list, consecutive_count: int
) -> list:
    """Finds consecutive overlapping slots i.e. end time of one slot overlaps with start time of another"""
    consecutive_slots_list = []
    parameter_sets = [(x, y) for x, y in itertools.product(dates, sports_centre_lists)]

    for target_date, venue in parameter_sets:
        venue = venue["encoded_alias"]
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        logging.debug(
            f"Extracting consecutive slots for venue slug: {venue} / date: {target_date}"
        )
        while True:
            consecutive_slots = []
            filtered_slots = [
                slot
                for slot in slots
                if slot["venue"] == venue and slot["date"] == target_date
            ]
            sorted_slots = sorted(
                filtered_slots, key=lambda slot: slot["parsed_start_time"]
            )
            logging.debug(sorted_slots)

            for i in range(len(sorted_slots) - 1):
                slot1 = sorted_slots[i]
                slot2 = sorted_slots[i + 1]

                if slot1["parsed_end_time"] >= slot2["parsed_start_time"]:
                    consecutive_slots.append(slot1)

                    if len(consecutive_slots) == consecutive_count - 1:
                        consecutive_slots.append(slot2)
                        break
                else:
                    consecutive_slots = []

            if len(consecutive_slots) == consecutive_count:
                consecutive_slots_list.append(consecutive_slots)
                # Remove the found slots from the data
                slots.remove(consecutive_slots[0])

            else:
                break  # No more consecutive slots found

    logging.debug(consecutive_slots_list)
    return consecutive_slots_list


@timeit
def parse_consecutive_slots(consecutive_slots):
    temp = []
    for consecutive_groupings in consecutive_slots:
        temp.append(
            {
                "venue": consecutive_groupings[0]["venue"],
                "date": consecutive_groupings[0]["date"],
                "consecutive_start_time": consecutive_groupings[0]["parsed_start_time"],
                "consecutive_end_time": consecutive_groupings[-1]["parsed_end_time"],
            }
        )
    return temp


if __name__ == "__main__":
    venue_name = "swiss-cottage-leisure-centre"
    target_date = date(2023, 9, 26)
    consecutive_count = 3

    consecutive_slots = find_consecutive_slots(
        venue_name, target_date, data_list, consecutive_count
    )
    print(consecutive_slots)
    print(parse_consecutive_slots(consecutive_slots))
