from typing import List
from fastapi import APIRouter, Query

from sportscanner.api.routers.geolocation.external import (
    get_nearest_postcode_from_coordinates,
    get_postcode_metadata,
    resolve_location_query,
    validate_uk_postcode,
    postcode_autocompletion,
)
from sportscanner.api.routers.geolocation.schemas import ResolvedLocationResponseModel

router = APIRouter()


@router.get("/validate-postcode")
async def validate_postcode_via_external_api(
    postcode: str = Query(None, description="Validate raw postcode")
):
    """Checking postcode validity"""
    is_valid = validate_uk_postcode(postcode)
    return {"valid": is_valid}


@router.get("/metadata-postcode")
async def get_postcode_metadata_via_external_api(
    postcode: str = Query(
        None, description="Validate and get metadata for raw postcode"
    )
):
    """Get metadata associated with postcode"""
    is_valid = validate_uk_postcode(postcode)
    return {"valid": is_valid, "metadata": get_postcode_metadata(postcode)}


@router.get("/autocomplete", response_model=List[str])
async def autocomplete_postcode(
    q: str = Query(..., description="Partial postcode to autocomplete"),
):
    """Return up to 5 postcode completions from postcodes.io"""
    return postcode_autocompletion(q, limit=5)


@router.get("/reverse")
async def reverse_geocode_to_postcode(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """Return the nearest UK postcode for a lat/lon coordinate."""
    postcode = get_nearest_postcode_from_coordinates(latitude=lat, longitude=lon)
    return {"postcode": postcode}


@router.get("/resolve-location", response_model=ResolvedLocationResponseModel)
async def resolve_flexible_location_query(
    q: str = Query(
        ...,
        description=(
            "Flexible location query: full postcode, outcode/district "
            "(for example `E14`), or London place name (for example `Paddington`)."
        ),
    ),
):
    """
    Resolve a flexible location query into a postcode and coordinates.

    This endpoint supports partial postcode and place-name questions used by the
    SportScanner agent before running venue/availability searches.
    """
    return resolve_location_query(q)
