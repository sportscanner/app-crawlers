from datetime import datetime
from typing import List
from rich import print
from urllib.parse import urljoin
import httpx
from fastapi import APIRouter, HTTPException, Path, Query
from sqlmodel import text
from starlette import status

from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.variables import *
from sportscanner.api.routers.core.schemas import *
import sportscanner.storage.postgres.database as db
from sportscanner.api.routers.health.schema import VenueAvailability

router = APIRouter()

# The sport param is interpolated as a TABLE NAME below, which can never be a bound
# SQL parameter — so it must be validated against an allow-list before it reaches the
# query string. This also doubles as the array-value allow-list for the `sports @>` filter.
_SPORT_TO_TABLE = {
    "badminton": "badminton",
    "squash": "squash",
    "pickleball": "pickleball",
    "padel": "padel",
}


@router.get("/scrapers") # /health/scrapers?sports=badminton
async def scrapers_healthcheck(
    sports: str = Query(..., description="Scraper sport category to check health for"),
) -> List[VenueAvailability]:
    # `sports` selects a TABLE NAME below, which can never be a bound SQL parameter —
    # it must be validated against the allow-list before it reaches the query string.
    # (The previous unvalidated version was also broken for a missing `sports`: an
    # f-string `FROM {sports}` with sports=None produced invalid SQL `FROM None t1`,
    # so this was never actually optional — making it required just matches reality.)
    if sports not in _SPORT_TO_TABLE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported sport category: {sports!r}. Must be one of {sorted(_SPORT_TO_TABLE)}",
        )
    table_name = _SPORT_TO_TABLE[sports]
    clause = text(f"""
        SELECT
            t2.venue_name,
            t1.date,
            MAX(t1.last_refreshed) AS latest_refresh
        FROM
            {table_name} t1
        JOIN
            sportsvenue t2 ON t1.composite_key = t2.composite_key
        WHERE
            t2.sports @> :sport_array ::varchar[]
        GROUP BY
            t1.composite_key,
            t2.venue_name,
            t1.date
        ORDER BY
            latest_refresh ASC,
            t2.venue_name;
    """).bindparams(sport_array=[sports])

    rows= db.get_all_rows(
        db.engine,
        None,
        clause
    )
    results: List[VenueDistanceModel] = [
        VenueAvailability(
            venue_name=row.venue_name,
            date=row.date,
            latest_refresh=row.latest_refresh
        )
        for row in rows
    ]
    return results

