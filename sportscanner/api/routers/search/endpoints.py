from sportscanner.api.routers.core.schemas import SportscannerSupportedSports
from sportscanner.logger import logging
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, Path
from rich import print
from starlette import status

import sportscanner.storage.postgres.database as db
from sportscanner.storage.postgres.tables import BadmintonMasterTable, SquashMasterTable, PickleballMasterTable, PadelMasterTable
from sportscanner.api.routers.search.schemas import SearchCriteria, SortByOptions
from sportscanner.api.routers.users.service.userService import UserService
from sportscanner.api.routers.venues.utils import get_venues_near_postcode
from sportscanner.crawlers.pipeline import *
from sportscanner.storage.postgres.dataset_transform import (
    group_slots_by_attributes,
    sort_and_format_grouped_slots_for_ui,
)

router = APIRouter()

def find_query_table(sport: SportscannerSupportedSports):
    if sport == SportscannerSupportedSports.BADMINTON:
        return BadmintonMasterTable
    elif sport == SportscannerSupportedSports.SQUASH:
        return SquashMasterTable
    elif sport == SportscannerSupportedSports.PICKLEBALL:
        return PickleballMasterTable
    elif sport == SportscannerSupportedSports.PADEL:
        return PadelMasterTable
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported sport category: {sport}",
        )

@router.post("/{sport}")
async def search(
    sport: SportscannerSupportedSports = Path(
        description="Sport category to filter venues and court availability"
    ),
    date: date =  Query(...,description="Date to filter court availability"),
    filters: SearchCriteria = ...,
):
    """Returns all court availability relevant to specified filters passed via payload"""
    queryTable = find_query_table(sport)

    try:
        nearby_venues = await get_venues_near_postcode(filters.postcode, filters.radius)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to fetch metadata - {filters.postcode} is not a valid UK postcode. Try changing the postcode to another one.",
        )
    if filters.analytics.specifiedVenues:
        composite_keys: List[str] = filters.analytics.specifiedVenues
    else:
        composite_keys = [venue.composite_key for venue in nearby_venues]

    current_timestamp = datetime.now()

    slots = db.get_all_rows(
        db.engine,
        None,
        db.select(queryTable)
        .where(queryTable.composite_key.in_(composite_keys))
        .where(queryTable.spaces > 0)  # Ignore empty courts
        .where(queryTable.starting_time >= filters.timeRange.starting)
        .where(queryTable.ending_time <= filters.timeRange.ending)
        .where(queryTable.date == date)
        .where(queryTable.starts_at > current_timestamp),
    )
    grouped_slots = group_slots_by_attributes(
        slots, attributes=("composite_key", "date")
    )
    distance_from_venues_reference = {
        venue.composite_key: venue.distance for venue in nearby_venues
    }
    _response = sort_and_format_grouped_slots_for_ui(
        grouped_slots, distance_from_venues_reference
    )
    # Function to sort the list based on API payload requirements
    sorted_response = sorted(
        _response,
        key=lambda x: (
            datetime.strptime(x["date"], "%a, %b %d"),  # Closest date
            float(x[filters.sortBy.name].replace("£", "")) if filters.sortBy == SortByOptions.price else x[filters.sortBy.name],
        ),
    )
    logging.warning(f"Time taken for retrieval, transformations, sorting: {datetime.now() - current_timestamp}")
    return sorted_response

@router.post("/{sport}/{composite_key}")
async def search(
    sport: SportscannerSupportedSports = Path(
        description="Sport category to filter venues and court availability"
    ),
    date: date =  Query(...,description="Date to filter court availability"),
    composite_key: str = Path(..., description="Composite key identifier to filter venue court availability")
):
    queryTable = find_query_table(sport)

    current_timestamp = datetime.now()

    slots = db.get_all_rows(
        db.engine,
        None,
        db.select(queryTable)
        .where(queryTable.composite_key == composite_key)
        .where(queryTable.spaces > 0)  # Ignore empty courts
        .where(queryTable.date == date)
        .where(queryTable.starts_at > current_timestamp),
    )
    return slots

