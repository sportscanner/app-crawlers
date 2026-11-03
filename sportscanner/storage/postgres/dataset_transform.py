import json
from datetime import date, datetime, time, timedelta
from itertools import groupby
from operator import attrgetter
from typing import List
from zoneinfo import ZoneInfo

import httpx
from PIL.TiffTags import lookup
from pydantic import BaseModel
from rich import print

import sportscanner.storage.postgres.database as db
import sportscanner.storage.postgres.tables
from sportscanner.cache import get_or_load_json as cache_get_or_load_json
from sportscanner.crawlers.pipeline import *

# Venue display metadata (name/address/organisation) is effectively static: it
# only changes when a venue is added. Kept well below any crawler cadence so a
# newly inserted venue appears without a deploy.
VENUE_LOOKUP_CACHE_KEY = "venue_lookup:v1"
VENUE_LOOKUP_TTL_SECONDS = 300


def _load_venue_lookup() -> dict:
    """Read venue display metadata once, without the geospatial columns.

    The old lookup selected whole SportsVenue rows (including the `srid`
    geometry) for every venue, on every request, purely to read three text
    fields. Selecting only what the UI uses keeps the payload small.
    """
    rows = db.get_all_rows(
        db.engine,
        None,
        db.select(
            sportscanner.storage.postgres.tables.SportsVenue.composite_key,
            sportscanner.storage.postgres.tables.SportsVenue.organisation,
            sportscanner.storage.postgres.tables.SportsVenue.venue_name,
            sportscanner.storage.postgres.tables.SportsVenue.address,
        ),
    )
    return {
        row.composite_key: {
            "organisation": row.organisation,
            "venue_name": row.venue_name,
            "address": row.address,
        }
        for row in rows
    }


def generate_venue_lookup() -> dict:
    """Venue metadata keyed by composite_key, cached across requests.

    This is the near-static contents of `sportsvenue` (only changes when a venue
    is added). Fetching it per request meant every search pulled the whole table
    from Postgres and rebuilt ~760 ORM objects before doing any real work.
    """
    return cache_get_or_load_json(
        VENUE_LOOKUP_CACHE_KEY, _load_venue_lookup, VENUE_LOOKUP_TTL_SECONDS
    )


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
        grouped_slots, distance_from_venues_reference, venue_lookup=None
        ) -> List[dict]:
    processed_slots: List = []
    # Was called once per group inside the loop below: a full `SELECT * FROM
    # sportsvenue` re-run for every distinct (venue, date) result, dominating
    # search latency (29 groups -> 29 redundant full-table round trips). Venue
    # metadata doesn't change per-group, so look it up once per call, and it is
    # cached across calls, so callers can pass the already-loaded dict in.
    lookup_dict = venue_lookup if venue_lookup is not None else generate_venue_lookup()
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
                    # Always None for badminton/squash (no such DB column -
                    # getattr's default covers that) and for padel/tennis/
                    # pickleball rows the crawler hasn't determined yet.
                    "indoor": getattr(x, "indoor", None),
                }
            )

        # Populating metadata from venues into main availability items. The
        # fallback keeps a slot whose venue row is missing from erroring out the
        # whole search.
        lookup_data = lookup_dict.get(earliest_slot_in_group.composite_key) or {}

        now_uk = datetime.now(ZoneInfo("Europe/London"))
        last_refreshed = earliest_slot_in_group.last_refreshed

        # Make last_refreshed timezone-aware in UK time if it's naive
        if last_refreshed.tzinfo is None:
            last_refreshed = last_refreshed.replace(tzinfo=ZoneInfo("Europe/London"))
        healthcheck = "deprecated" if now_uk - last_refreshed > timedelta(minutes=30) else "ok"

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
                "last_refreshed": earliest_slot_in_group.last_refreshed.isoformat(),
                "healthcheck": healthcheck
            }
        )
    return processed_slots
