import json
from datetime import date, time, timedelta
from itertools import groupby
from operator import attrgetter
from typing import List

import httpx
from PIL.TiffTags import lookup
from pydantic import BaseModel
from rich import print

import sportscanner.storage.postgres.database as db
import sportscanner.storage.postgres.tables
from sportscanner.crawlers.pipeline import *


def generate_venue_lookup() -> dict:
    venues: List[sportscanner.storage.postgres.tables.SportsVenue] = db.get_all_sports_venues(db.engine)
    reference_dict = {
        venue.composite_key: {
            "organisation": venue.organisation,
            "venue_name": venue.venue_name,
            "address": venue.address,
        }
        for venue in venues
    }
    return reference_dict


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
    grouped = groupby(
        slots_sorted, key=lambda slot: tuple(getattr(slot, attr) for attr in attributes)
    )

    # Convert to a list of lists
    grouped_slots = [list(group) for _, group in grouped]
    return grouped_slots


def sort_and_format_grouped_slots_for_ui(
        grouped_slots, distance_from_venues_reference
        ) -> List[dict]:
    processed_slots: List = []
    for groups in grouped_slots:
        # Sort the groups based on 'date' and 'starting_time'
        sorted_slots_in_group = sorted(
            groups, key=attrgetter("date", "starting_time")
        )

        # Find the first slot with spaces > 0
        sorted_slots_with_spaces = next(
            (
                sorted_slots_in_group[i:]
                for i, elem in enumerate(sorted_slots_in_group)
                if elem.spaces > 0
            ),
            [],  # Default to empty list if no slot with spaces > 0 is found
        )
        # If there are no slots with available spaces, skip the group
        if not sorted_slots_with_spaces:
            continue
        # Get the earliest slot in the group (the first element in sorted list with spaces > 0)
        earliest_slot_in_group: sportscanner.storage.postgres.tables.BadmintonMasterTable = sorted_slots_with_spaces[0]
        availabilities = []
        for x in sorted_slots_with_spaces:
            _available: bool = True if x.spaces > 0 else False
            availabilities.append(
                {
                    "startingTime": x.starting_time.strftime("%H:%M"),
                    "endingTime": x.ending_time.strftime("%H:%M"),
                    "available": _available,
                    "bookingUrl": x.booking_url,
                    "price": x.price,
                }
            )

        # Populating metadata from venues into main availability items
        lookup_dict = generate_venue_lookup()
        lookup_data = lookup_dict.get(earliest_slot_in_group.composite_key, None)
        processed_slots.append(
            {
                "composite_key": earliest_slot_in_group.composite_key,
                "venue": lookup_data.get("venue_name", ""),
                "address": lookup_data.get("address", ""),
                "distance": distance_from_venues_reference.get(
                    earliest_slot_in_group.composite_key, 99
                ),
                "price": earliest_slot_in_group.price,
                "organization": lookup_data.get("organisation", ""),
                "date": earliest_slot_in_group.date.strftime("%a, %b %d"),
                "availability": availabilities,
            }
        )
    return processed_slots
