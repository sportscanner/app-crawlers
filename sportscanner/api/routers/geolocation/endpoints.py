from typing import Optional

from fastapi import APIRouter, Query
from sportscanner.api.routers.geolocation.schemas import PostcodesResponseModel

from sportscanner.api.routers.geolocation.external import validate_uk_postcode, get_postcode_metadata
from sportscanner.api.routers.geolocation.utils import *
import httpx

router = APIRouter()

@router.get("/validate-postcode")
async def validate_postcode_via_external_api(postcode: str = Query(None, description="Raw postcode to be checked for validity")):
    """Checking postcode validity"""
    is_valid = validate_uk_postcode(postcode)
    return {
        "valid": is_valid
    }

@router.get("/metadata-postcode")
async def get_postcode_metadata_via_external_api(postcode: str = Query(None, description="Raw postcode to be checked for metadata")):
    """Get metadata associated with postcode"""
    is_valid = validate_uk_postcode(postcode)
    return {
        "valid": is_valid,
        "metadata": get_postcode_metadata(postcode)
    }


@router.get("/venues-near-postcode")
async def venues_near_postcode(postcode: str = Query(None, description="Raw postcode to be checked for metadata")):
    """Get metadata associated with postcode"""
    search_postcode_metadata: Optional[PostcodesResponseModel] = get_postcode_metadata(postcode)
    if search_postcode_metadata is not None:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:8000/venues/")
            json_response = response.json()
        sports_venues = json_response.get("venues")
        distance_from_venues = []
        for sports_venue in sports_venues:
            _dist = calculate_distance_in_miles(
                locationA=(
                    search_postcode_metadata.result.longitude,
                    search_postcode_metadata.result.latitude,
                ),
                locationB=(sports_venue["longitude"], sports_venue["latitude"]),
            )
            distance_from_venues.append(
                {
                    "distance": _dist,
                    "venue": sports_venue
                }
            )
        distance_from_venues = sorted(distance_from_venues, key=lambda x: x["distance"])
        return {
            "status": "OK",
            "message": "Venues returned successfully",
            "data": distance_from_venues
        }
    else:
        return {
            "status": "OK",
            "message": f"Postcode metadata not fetched correctly: {postcode}",
            "data": []
        }
