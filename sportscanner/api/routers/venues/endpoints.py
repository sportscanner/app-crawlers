from sportscanner.api.routers.venues.utils import get_venues_from_database
from fastapi import APIRouter, Query
from datetime import datetime

router = APIRouter()

@router.get("/")
async def get_venues(
    limit: int = Query(None, description="Limit the number of venues in the response"),
):
    """Get all Books"""
    sports_centre_names, sports_venues = get_venues_from_database()
    output = sports_venues[:limit] if limit is not None else sports_venues
    return {
        "timestamp": datetime.now(),
        "size": len(output),
        "venues": output
    }
