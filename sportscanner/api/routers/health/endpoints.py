from datetime import datetime
from typing import List
from rich import print
from urllib.parse import urljoin
import httpx
from fastapi import APIRouter, Path, Query
from sqlmodel import text

from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.variables import *
from sportscanner.api.routers.core.schemas import *
import sportscanner.storage.postgres.database as db
from sportscanner.api.routers.health.schema import VenueAvailability

router = APIRouter()


@router.get("/scrapers") # /venues/near?postcode=SE17TP&distance=5.0
async def scrapers_healthcheck(
    sports: Optional[str] = Query(None, description="Scraper sport category to check health for"),
) -> List[VenueAvailability]:
    sport_array = f"ARRAY['{sports}']::varchar[]" if sports else "ARRAY[]::varchar[]"
    clause: str = f"""
        SELECT
            t2.venue_name,
            t1.date,
            MIN(t1.last_refreshed) AS latest_refresh
        FROM
            {sports} t1
        JOIN
            sportsvenue t2 ON t1.composite_key = t2.composite_key
        WHERE
            t2.sports @> {sport_array}
        GROUP BY
            t1.composite_key,
            t2.venue_name,
            t1.date
        ORDER BY
            latest_refresh ASC,
            t2.venue_name;
    """
    
    rows= db.get_all_rows(
        db.engine, 
        None, 
        text(clause)
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

