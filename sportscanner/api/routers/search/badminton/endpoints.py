from fastapi import APIRouter, Query
import sportscanner.storage.postgres.database as db
from pydantic import BaseModel
from sportscanner.crawlers.pipeline import *
from datetime import date, timedelta
import httpx
from rich import print
from sportscanner.variables import settings, urljoin
from sqlmodel import col
from typing import List, Optional

router = APIRouter()

class Filters(BaseModel):
    postcode: str
    slugs: List[str]
    dateRange: List[date]
    timeSlots: List
    consecutiveSlots: int
    allLocations: bool
    sortBy: str


@router.post("/")
async def availability(filters: Filters):
    """Returns court availability as per advanced filters passed in payload"""
    async with httpx.AsyncClient() as client:
        response = await client.get(urljoin(settings.API_BASE_URL, f"/geolocation/?postcode{filters.postcode}"))
        json_response = response.json()
    if json_response.get("data"):
        return {
            "status": "OK",
            "message": f"No venues found within 10 miles of postcode: {filters.postcode}",
            "slots": []
        }
    else:
        return {
            "status": "OK",
            "message": f"No venues found within 10 miles of postcode: {filters.postcode}",
            "slots": []
        }


@router.get("/")
async def search(
    postcode: str = Query(None, description="Raw postcode to find nearby venues"),
    distance: Optional[float] = Query(10.0, description="Fetch venues within defined radius (in miles)")
):
    """Returns all court availability within `x` miles of a postcode"""
    async with httpx.AsyncClient() as client:
        response = await client.get(urljoin(
            settings.API_BASE_URL, f"/geolocation/venues-near-postcode?postcode={postcode}&distance={distance}")
        )
        json_response = response.json()
    if json_response.get("data"):
        data = json_response.get("data")
        slugs = [x["venue"]["slug"] for x in data]
        slots = db.get_all_rows(
            engine,
            db.SportScanner,
            db.select(db.SportScanner)
            .where(db.SportScanner.venue_slug.in_(slugs))
            .order_by(db.SportScanner.date)
            .order_by(db.SportScanner.starting_time)
        )
        return {
            "status": "OK",
            "message": f"Availability found within {distance} miles of postcode",
            "slots": slots
        }
    else:
        return {
            "status": "OK",
            "message": f"No venues found within {distance} miles of postcode",
            "slots": []
        }

# @router.get("/latest/")
# async def trigger_search(filters: Filters):
#     """Trigger fresh dataset refresh for specific venues and dates"""
#     results: List[UnifiedParserSchema] = await standalone_refresh_trigger(dates=filters.dates, venues_slugs=filters.slugs)
#     return {
#         "statusCode": 200,
#         "success": True,
#         "message": "Partial dataset refresh triggered",
#         "data": {
#             "found": len(results),
#             "slots": results
#         }
#     }
#
#
# @router.get("/full-refresh/")
# async def refresh_dataset():
#     """Trigger fresh dataset refresh for all venues for next 1 week"""
#     today = date.today()
#     dates = [today + timedelta(days=i) for i in range(6)]
#     async with httpx.AsyncClient() as client:
#         response = await client.get(urljoin(settings.API_BASE_URL, "/venues/"))
#         json_response = response.json()
#     sports_venues: List[SportsVenue] = json_response.get("venues")
#     results = await full_data_refresh_pipeline(sports_venues)
#     return {
#         "statusCode": 200,
#         "success": True,
#         "message": "Full dataset refresh triggered",
#         "data": {
#             "found": len(results),
#             "slots": results
#         }
#     }
