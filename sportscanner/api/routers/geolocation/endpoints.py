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