from typing import Optional

from fastapi import APIRouter, Query
from sportscanner.api.routers.geolocation.schemas import PostcodesResponseModel

from sportscanner.api.routers.geolocation.external import validate_uk_postcode, get_postcode_metadata
from sportscanner.api.routers.geolocation.utils import *
import httpx
from sportscanner.variables import settings, urljoin

router = APIRouter()

@router.get("/validate-postcode")
async def validate_postcode_via_external_api(postcode: str = Query(None, description="Validate raw postcode")):
    """Checking postcode validity"""
    is_valid = validate_uk_postcode(postcode)
    return {
        "valid": is_valid
    }

@router.get("/metadata-postcode")
async def get_postcode_metadata_via_external_api(postcode: str = Query(None, description="Validate and get metadata for raw postcode")):
    """Get metadata associated with postcode"""
    is_valid = validate_uk_postcode(postcode)
    return {
        "valid": is_valid,
        "metadata": get_postcode_metadata(postcode)
    }


@router.get("/venues-near-postcode")
async def venues_near_postcode(
        postcode: str = Query(None, description="Raw postcode to find nearby venues"),
        distance: Optional[float] = Query(10.0, description="Fetch venues within defined radius (in miles)")
    ):
    """Get metadata associated with postcode"""
    search_postcode_metadata: Optional[PostcodesResponseModel] = get_postcode_metadata(postcode)
    print(urljoin(settings.API_BASE_URL, "/venues"))
    if search_postcode_metadata is not None:
        async with httpx.AsyncClient() as client:
            response = await client.get(urljoin(settings.API_BASE_URL, "/venues/"))
            print(response)
            json_response = response.json()
        sports_venues = json_response.get("venues")
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
