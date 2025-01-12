from aiohttp.web_response import json_response
from fastapi import APIRouter
import sportscanner.crawlers.database as db
from pydantic import BaseModel
from sportscanner.crawlers.pipeline import *
from datetime import date, timedelta
import httpx

router = APIRouter()

class Filters(BaseModel):
    slugs: List[str]
    dates: List[date]


@router.get("/")
async def availability():
    """CRON pipeline dataset fetched (cache)"""
    slots = db.get_all_rows(
        engine,
        db.SportScanner,
        db.select(db.SportScanner)
        .where(db.SportScanner.spaces > 0)
        # .where(db.SportScanner.starting_time >= start_time_filter_input)
        # .where(db.SportScanner.ending_time <= end_time_filter_input)
        # .where(db.SportScanner.date >= starting_date_input)
        # .where(db.SportScanner.date <= ending_date_input)
        .order_by(db.SportScanner.date)
        .order_by(db.SportScanner.starting_time),
    )
    return {
        "statusCode": 200,
        "success": True,
        "message": "Pre-fetched dataset returned",
        "data": {
            "found": len(slots),
            "slots": slots
        }
    }


@router.get("/latest/")
async def trigger_search(filters: Filters):
    """Trigger fresh dataset refresh for specific venues and dates"""
    results: List[UnifiedParserSchema] = await standalone_refresh_trigger(dates=filters.dates, venues_slugs=filters.slugs)
    return {
        "statusCode": 200,
        "success": True,
        "message": "Partial dataset refresh triggered",
        "data": {
            "found": len(results),
            "slots": results
        }
    }


@router.get("/refresh/")
async def refresh_dataset():
    """Trigger fresh dataset refresh for all venues for next 1 week"""
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(6)]
    async with httpx.AsyncClient() as client:
        response = await client.get("http://localhost:8000/venues/")
        json_response = response.json()
    sports_venues: List[SportsVenue] = json_response.get("venues")
    results = await full_data_refresh_pipeline(sports_venues)
    return {
        "statusCode": 200,
        "success": True,
        "message": "Full dataset refresh triggered",
        "data": {
            "found": len(results),
            "slots": results
        }
    }
