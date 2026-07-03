"""MCP tool: find available courts near a postcode for a given sport/date."""

from datetime import datetime
from typing import Annotated, List

import httpx
from pydantic import Field

import sportscanner.storage.postgres.database as db
from sportscanner.api.routers.venues.utils import get_sports_venues_within_radius
from sportscanner.storage.postgres.dataset_transform import (
    group_slots_by_attributes,
    sort_and_format_grouped_slots_for_ui,
)
from sportscanner.storage.postgres.tables import (
    BadmintonMasterTable,
    PadelMasterTable,
    PickleballMasterTable,
    SquashMasterTable,
)

_TABLES = {
    "badminton": BadmintonMasterTable,
    "squash": SquashMasterTable,
    "pickleball": PickleballMasterTable,
    "padel": PadelMasterTable,
}


def _geocode_postcode(postcode: str):
    response = httpx.get(
        f"https://api.postcodes.io/postcodes/{postcode.strip()}", timeout=10
    )
    if response.status_code != 200:
        return None, None
    result = response.json().get("result") or {}
    return result.get("longitude"), result.get("latitude")


def find_available_courts(
    sport: Annotated[
        str,
        Field(description="Sport to search: 'badminton', 'squash', 'pickleball' or 'padel'"),
    ],
    postcode: Annotated[
        str, Field(description="UK postcode to search around, e.g. 'SE1 8UL'")
    ],
    date: Annotated[str, Field(description="Date to search, in YYYY-MM-DD format")],
    radius_miles: Annotated[
        float, Field(description="Search radius in miles from the postcode")
    ] = 3.0,
) -> List[dict]:
    """
    Find available court slots for a sport near a UK postcode on a given date.

    Returns venues (nearest first) with their available time slots, price,
    distance and a direct booking URL for each slot.
    """
    sport_key = sport.strip().lower()
    query_table = _TABLES.get(sport_key)
    if query_table is None:
        raise ValueError(
            f"Unsupported sport '{sport}'. Choose from: {', '.join(_TABLES)}"
        )
    try:
        search_date = datetime.strptime(date.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("date must be in YYYY-MM-DD format, e.g. 2026-07-05")

    longitude, latitude = _geocode_postcode(postcode)
    if longitude is None or latitude is None:
        raise ValueError(f"'{postcode}' is not a valid UK postcode")

    nearby = get_sports_venues_within_radius(
        longitude=longitude,
        latitude=latitude,
        distance=radius_miles,
        sport_category=sport_key,
    )
    if not nearby:
        return []

    distance_reference = {
        item["venue"].composite_key: item["distance"] for item in nearby
    }
    composite_keys = list(distance_reference.keys())

    now = datetime.now()
    slots = db.get_all_rows(
        db.engine,
        None,
        db.select(query_table)
        .where(query_table.composite_key.in_(composite_keys))
        .where(query_table.spaces > 0)
        .where(query_table.date == search_date),
    )
    grouped_slots = group_slots_by_attributes(
        slots, attributes=("composite_key", "date")
    )
    return sort_and_format_grouped_slots_for_ui(grouped_slots, distance_reference)
