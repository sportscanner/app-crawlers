from sportscanner.api.routers.venues.utils import get_venues_from_database
from fastapi import APIRouter, Query, Path
from datetime import datetime
from sportscanner.variables import *
import httpx
from sportscanner.api.routers.geolocation.schemas import PostcodesResponseModel
from sportscanner.api.routers.geolocation.utils import *


router = APIRouter()

@router.get("/")
async def get_all_venues(
    limit: int = Query(None, description="Limit the number of venues in the response"),
):
    """Get all Books"""
    sports_centre_names, sports_venues = get_venues_from_database()
    output = sports_venues[:limit] if limit is not None else sports_venues
    return {
        "status": "OK",
        "message": f"All venues returned from database",
        "data": output
    }


@router.get("/near")
async def venues_near_postcode_and_radius(
        postcode: str = Query(None, description="Raw postcode to find nearby venues"),
        distance: Optional[float] = Query(10.0, description="Fetch venues within defined radius (in miles)")
    ):
    """Get metadata associated with postcode"""
    if postcode is not None:
        async with httpx.AsyncClient() as client:
            response = await client.get(urljoin(settings.API_BASE_URL, f"/geolocation/metadata-postcode?postcode={postcode}"))
            json_response = response.json()
        json_metadata = json_response.get("metadata")
        search_postcode_metadata: Optional[PostcodesResponseModel] = PostcodesResponseModel(**json_metadata)
        async with httpx.AsyncClient() as client:
            response = await client.get(urljoin(settings.API_BASE_URL, "/venues/"))
            json_response = response.json()
        sports_venues = json_response.get("data")
        venues_distance_from_postcode = []
        for sports_venue in sports_venues:
            _dist = calculate_distance_in_miles(
                locationA=(
                    search_postcode_metadata.result.longitude,
                    search_postcode_metadata.result.latitude,
                ),
                locationB=(sports_venue["longitude"], sports_venue["latitude"]),
            )
            venues_distance_from_postcode.append(
                {
                    "distance": _dist,
                    "venue": sports_venue
                }
            )
        venues_distance_from_postcode = sorted(venues_distance_from_postcode, key=lambda x: x["distance"])
        venues_within_defined_radius = list(filter(lambda x: x["distance"] <= distance, venues_distance_from_postcode))
        if venues_within_defined_radius:
            return {
                "status": "OK",
                "message": f"Venues within {distance} miles returned successfully",
                "data": venues_within_defined_radius
            }
        else:
            return {
                "status": "OK",
                "message": f"No venues found within {distance} mile radius",
                "data": []
            }
    else:
        return {
            "status": "OK",
            "message": f"Postcode metadata not fetched correctly: {postcode}",
            "data": []
        }


@router.get("/{composite}")
async def get_venue_info(
    composite: str = Path(description="Composite key identifier to fetch venue information"),
):
    """Get all Books"""
    sports_centre_names, sports_venues = get_venues_from_database()
    output = [x for x in sports_venues if x.composite_key==composite]
    return {
        "status": "OK",
        "message": f"Venue information returned for: {composite}",
        "data": output
    }
