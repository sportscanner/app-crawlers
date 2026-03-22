from typing import Optional, List

import httpx
from fastapi import APIRouter, Query

from sportscanner.api.routers.geolocation.external import (
    get_postcode_metadata,
    validate_uk_postcode,
    postcode_autocompletion,
)
from sportscanner.api.routers.geolocation.schemas import PostcodesResponseModel
from sportscanner.api.routers.geolocation.utils import *
from sportscanner.variables import settings, urljoin

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
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.postcodes.io/postcodes?lon={lon}&lat={lat}&limit=1"
        )
    data = resp.json()
    results = data.get("result") or []
    if results:
        return {"postcode": results[0]["postcode"]}
    return {"postcode": None}
