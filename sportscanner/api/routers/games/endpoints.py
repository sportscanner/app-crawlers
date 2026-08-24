from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from rich import print
from starlette import status

import sportscanner.storage.postgres.database as db
from sportscanner.api.routers.core.schemas import SportscannerSupportedSports
from sportscanner.api.routers.search.endpoints import find_query_table
from sportscanner.logger import logging
from sportscanner.storage.postgres.tables import SportsVenue

router = APIRouter()

# Organisations whose slots are social games / sessions (booked per-person with
# a fixed number of spots) rather than whole-court bookings. These are excluded
# from court-search results and surfaced through /games instead, where the UI
# can show "X spots remaining" from the `spaces` column.
GAMES_ORGANISATIONS = {"Lemon Pickleball"}


@router.get("")
async def games(
    sport: SportscannerSupportedSports = Query(
        description="Sport category to list games for"
    ),
    date: Optional[date] = Query(
        None, description="Optional date to filter games (defaults to all upcoming)"
    ),
):
    """Returns social game sessions (per-person bookings with limited spots)
    for the given sport, with remaining spots per session."""
    query_table = find_query_table(sport)
    current_timestamp = datetime.now()

    statement = (
        db.select(
            query_table.composite_key,
            query_table.date,
            query_table.starting_time,
            query_table.ending_time,
            query_table.price,
            query_table.spaces,
            query_table.capacity,
            query_table.booking_url,
            SportsVenue.organisation,
            SportsVenue.venue_name,
            SportsVenue.address,
            SportsVenue.postcode,
            SportsVenue.latitude,
            SportsVenue.longitude,
        )
        .join(SportsVenue, query_table.composite_key == SportsVenue.composite_key)
        .where(SportsVenue.organisation.in_(GAMES_ORGANISATIONS))
        .where(query_table.spaces > 0)
        .where(query_table.starts_at > current_timestamp)
        .order_by(query_table.date, query_table.starting_time)
    )
    if date is not None:
        statement = statement.where(query_table.date == date)

    rows = db.get_all_rows(db.engine, None, statement)

    return [
        {
            "composite_key": row.composite_key,
            "organisation": row.organisation,
            "venue": row.venue_name,
            "address": row.address,
            "postcode": row.postcode,
            "latitude": row.latitude,
            "longitude": row.longitude,
            "date": row.date.isoformat(),
            "startingTime": row.starting_time.strftime("%H:%M"),
            "endingTime": row.ending_time.strftime("%H:%M"),
            "price": row.price,
            "spotsRemaining": row.spaces,
            "spotsTotal": row.capacity,
            "bookingUrl": row.booking_url,
        }
        for row in rows
    ]
