from fastapi import APIRouter, Query

from sportscanner.api.routers.geolocation.external import validate_uk_postcode, get_postcode_metadata

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
