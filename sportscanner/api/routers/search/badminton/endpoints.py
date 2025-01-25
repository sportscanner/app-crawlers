from idlelib.editor import darwin

from fastapi import APIRouter, Query, Request
import sportscanner.storage.postgres.database as db
from sportscanner.storage.postgres.dataset_transform import group_slots_by_attributes, sort_and_format_grouped_slots_for_ui
from pydantic import BaseModel
from sportscanner.crawlers.pipeline import *
from datetime import date, timedelta, datetime
import httpx
from rich import print
from sportscanner.variables import settings, urljoin
from sportscanner.api.routers.search.badminton.schemas import SearchCriteria
from sqlmodel import col
from typing import List, Optional
from itertools import groupby
from operator import attrgetter


router = APIRouter()


@router.post("/")
async def search(filters: SearchCriteria):
    """Returns all court availability relevant to specified filters passed via payload"""
    print(filters)
    async with httpx.AsyncClient() as client:
        response = await client.get(
            urljoin(
                settings.API_BASE_URL,
                f"/venues/near?postcode={filters.postcode}&distance={filters.radius}"
            )
        )
        json_response = response.json()
    if json_response.get("data"):
        data = json_response.get("data")
        composite_keys = [x["venue"]["composite_key"] for x in data]
        slots = db.get_all_rows(
            engine,
            db.SportScanner,
            db.select(db.SportScanner)
            .where(db.SportScanner.composite_key.in_(composite_keys))
            .where(db.SportScanner.spaces > 0) # For now ignoring any empty courts (might use for analytics)
            # .where(db.SportScanner.starting_time >= datetime.now().time()) # Shouldn't show any historic values
            .where(db.SportScanner.starting_time >= filters.timeRange.starting)
            .where(db.SportScanner.ending_time <= filters.timeRange.ending)
            .where(db.SportScanner.date >= datetime.now().date()) # Shouldn't show any historic values
            .where(db.SportScanner.date >= filters.dateRange.starting)
            .where(db.SportScanner.date <= filters.dateRange.ending)
        )
        grouped_slots = group_slots_by_attributes(slots, attributes=("composite_key", "date"))
        distance_from_venues_reference = {x["venue"]["composite_key"]: x["distance"] for x in data}
        _response = sort_and_format_grouped_slots_for_ui(grouped_slots, distance_from_venues_reference)
        # Function to sort the list
        sorted_response = sorted(
            _response,
            key=lambda x: (
                datetime.strptime(x['date'], '%a, %b %d'),  # Closest date
                x['distance']  # Shortest location
            )
        )
        return {
            "success": True,
            "resultId": f"e34f27a2-d591-486c-9a38-11111",
            "slots": sorted_response
        }
    else:
        return {
            "success": True,
            "resultId": f"e34f27a2-d591-486c-9a38-00000",
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
#     # today = date.today()
#     # dates = [today + timedelta(days=i) for i in range(6)]
#     # async with httpx.AsyncClient() as client:
#     #     response = await client.get(urljoin(settings.API_BASE_URL, "/venues/"))
#     #     json_response = response.json()
#     # sports_venues: List[SportsVenue] = json_response.get("venues")
#     results = await full_data_refresh_pipeline()
#     return {
#         "statusCode": 200,
#         "success": True,
#         "message": "Full dataset refresh triggered",
#         "data": {
#             "found": len(results),
#             "slots": results
#         }
#     }
