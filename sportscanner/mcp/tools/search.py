"""MCP court search uses the same filters and availability rules as REST."""

from datetime import date as Date, time
from typing import Annotated, Literal

from pydantic import Field

from sportscanner.api.routers.core.schemas import SportscannerSupportedSports
from sportscanner.api.routers.search.endpoints import search_courts
from sportscanner.api.routers.search.schemas import (
    AdvancedFiltersCriteria,
    SearchCriteria,
    SortByOptions,
    TimeFilter,
)


async def find_available_courts(
    sport: SportscannerSupportedSports,
    postcode: Annotated[
        str, Field(min_length=1, description="UK postcode, e.g. SE1 8UL")
    ],
    date: Annotated[
        Date, Field(description="Search date as YYYY-MM-DD, Europe/London")
    ],
    radius_miles: Annotated[
        float, Field(gt=0, le=50, description="Radius in miles")
    ] = 3.0,
    starting_time: Annotated[
        time, Field(description="Earliest start, local HH:MM")
    ] = time(0, 0),
    ending_time: Annotated[time, Field(description="Latest end, local HH:MM")] = time(
        23, 59
    ),
    indoor: Annotated[
        bool | None, Field(description="Indoor/outdoor filter; omit for any")
    ] = None,
    sort_by: Literal["distance", "price"] = "distance",
) -> list[dict]:
    """Find available badminton, squash, pickleball, padel or tennis courts.

    Returns venue, distance in miles, GBP prices, freshness and provider booking
    links. Times use Europe/London. Social games and past slots are excluded.
    Availability is a snapshot, not a reservation. Booking happens with the
    provider and may require the user's account. No payment or booking is made.
    """
    if starting_time >= ending_time:
        raise ValueError("starting_time must be before ending_time")
    return await search_courts(
        sport=sport,
        date=date,
        filters=SearchCriteria(
            postcode=postcode,
            radius=radius_miles,
            timeRange=TimeFilter(starting=starting_time, ending=ending_time),
            analytics=AdvancedFiltersCriteria(),
            sortBy=SortByOptions(sort_by),
            indoor=indoor,
        ),
    )
