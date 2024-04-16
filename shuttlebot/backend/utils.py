import itertools
import sys
from datetime import date, datetime, time
from time import time as timer
from typing import Dict, List, Optional
from functools import wraps

import pandas as pd
from loguru import logger as logging
from pydantic import BaseModel, ValidationError
from shuttlebot.backend.database import engine, SportScanner, get_all_rows, SportsVenue
from sqlmodel import select

from rich import print
from shuttlebot import config


def timeit(func):
    """Calculates the execution time of the function on top of which the decorator is assigned"""

    @wraps(func)
    def wrap_func(*args, **kwargs):
        tic = timer()
        result = func(*args, **kwargs)
        tac = timer()
        logging.info(f"Function {func.__name__!r} executed in {(tac - tic):.4f}s")
        return result

    return wrap_func


class ConsecutiveSlotsCarousalDisplay(BaseModel):
    """Model to store information displayed via Card carousal"""
    venue: str
    date: date
    consecutive_start_time: time
    consecutive_end_time: time
    slots_starting_times: str


def async_timer(func):
    """Calculates the execution time of the Async function on top of which the decorator is assigned"""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        tic = timer()
        result = await func(*args, **kwargs)
        tac = timer()
        logging.debug(f"Function {func.__name__!r} executed in {(tac - tic):.4f}s")
        return result

    return wrapper


@timeit
def find_consecutive_slots(consecutive_count: int) -> List[List[SportScanner]]:
    """Finds consecutively overlapping slots i.e. end time of one slot overlaps with start time of
    another and calculates the `n` consecutive slots
    Returns: List of grouped consecutively occurring slots
    """

    slots = get_all_rows(engine, SportScanner, select(SportScanner).where(SportScanner.spaces > 0))
    sports_centre_lists = get_all_rows(engine, SportsVenue, select(SportsVenue))
    dates: List[date] = list(set([row.date for row in slots]))
    consecutive_slots_list = []
    parameter_sets = [(x, y) for x, y in itertools.product(dates, sports_centre_lists)]

    for target_date, venue in parameter_sets:
        venue = venue.slug
        logging.debug(
            f"Extracting consecutive slots for venue slug: {venue} / date: {target_date}"
        )
        while True:
            consecutive_slots = []
            filtered_slots = [
                slot
                for slot in slots
                if slot.venue_slug == venue and slot.date == target_date
            ]
            sorted_slots = sorted(
                filtered_slots, key=lambda slot: slot.starting_time
            )
            logging.debug(sorted_slots)

            for i in range(len(sorted_slots) - 1):
                slot1 = sorted_slots[i]
                slot2 = sorted_slots[i + 1]

                if slot1.ending_time >= slot2.starting_time:
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

    logging.debug(f"Top 3 Consecutive slots calculations:\n{consecutive_slots_list[:3]}")
    return consecutive_slots_list


@timeit
def format_consecutive_slots_groupings(consecutive_slots: List[List[SportScanner]]) -> List[Dict]:
    temp = []
    for group_for_consecutive_slots in consecutive_slots:
        gather_slots_starting_times = []
        for slot in group_for_consecutive_slots:
            gather_slots_starting_times.append(
                slot.starting_time.strftime("%H:%M")
            )
        display_message_slots_starting_times: str = ("Slots starting at "
                                                     f"{', '.join(gather_slots_starting_times)}")

        temp.append(
            ConsecutiveSlotsCarousalDisplay(
                venue=group_for_consecutive_slots[0].venue_slug,
                date=group_for_consecutive_slots[0].date,
                consecutive_start_time=group_for_consecutive_slots[0].starting_time,
                consecutive_end_time=group_for_consecutive_slots[-1].ending_time,
                slots_starting_times=display_message_slots_starting_times
            )
        )
    logging.info(f"Top 3 formatted consecutive slot groupings for Carousal:\n{temp[:3]}")
    return temp


if __name__ == "__main__":
    """Write a test here for calculating consecutive slots"""
    logging.info("This scripts cannot be called standalone for now")
