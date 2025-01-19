
import sportscanner.storage.postgres.database as db
from pydantic import BaseModel
from sportscanner.crawlers.pipeline import *
from datetime import date, timedelta, time
import httpx
from rich import print
from itertools import groupby
from operator import attrgetter
from typing import List
import json

def group_slots_by_attributes(slots, attributes):
    """
    Group rows into a list of lists based on multiple attributes.

    :param slots: List of objects to group.
    :param attributes: List or tuple of attribute names to group by.
    :return: List of grouped lists.
    """
    # Sort the slots by the attributes to ensure proper grouping
    slots_sorted = sorted(slots, key=attrgetter(*attributes))

    # Group the slots based on the attributes
    grouped = groupby(slots_sorted, key=lambda slot: tuple(getattr(slot, attr) for attr in attributes))

    # Convert to a list of lists
    grouped_slots = [list(group) for _, group in grouped]
    return grouped_slots

def sort_and_format_grouped_slots_for_ui(grouped_slots):
    # print(grouped_slots)
    processed_slots: List = []
    for groups in grouped_slots:
        # Sort the groups based on 'date' and 'starting_time'
        sorted_slots_in_group: List[db.SportScanner] = sorted(groups, key=attrgetter("date", "starting_time"))

        # Find the first slot with spaces > 0
        sorted_slots_with_spaces = next(
            (sorted_slots_in_group[i:] for i, elem in enumerate(sorted_slots_in_group) if elem.spaces > 0),
            []  # Default to empty list if no slot with spaces > 0 is found
        )
        # If there are no slots with available spaces, skip the group
        if not sorted_slots_with_spaces:
            continue
        # Get the earliest slot in the group (the first element in sorted list with spaces > 0)
        earliest_slot_in_group: db.SportScanner = sorted_slots_with_spaces[0]
        sorted_slots_without_element_zero: List[db.SportScanner] = [x for i, x in enumerate(sorted_slots_in_group) if i != 0]
        otherSlots = []
        for x in sorted_slots_without_element_zero:
            _available: bool = True if x.spaces > 0 else False
            otherSlots.append(
                {
                    "time": x.starting_time.strftime('%H:%M'),
                    "available": _available
                }
            )
        processed_slots.append(
            {
                "startTime": earliest_slot_in_group.starting_time.strftime('%H:%M'),
                "endTime": earliest_slot_in_group.ending_time.strftime('%H:%M'),
                "location": earliest_slot_in_group.venue_slug,
                "distance": 1.8,
                "price": 15.0,
                "organization": earliest_slot_in_group.organisation,
                "date": earliest_slot_in_group.date.strftime('%a, %b %d'),
                "otherSlots": otherSlots
            }
        )
    print(json.dumps(processed_slots, indent=4))


slots = db.get_all_rows(
    engine,
    db.SportScanner,
    db.select(db.SportScanner)
    # .where(db.SportScanner.spaces > 0)
    # .order_by(db.SportScanner.date)
    # .order_by(db.SportScanner.starting_time)
)

grouped_slots = group_slots_by_attributes(slots, attributes=("organisation", "venue_slug", "date"))
# print(grouped_slots)
sort_and_format_grouped_slots_for_ui(grouped_slots)
# print(grouped_slots)