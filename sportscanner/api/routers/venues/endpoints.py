from datetime import datetime
from typing import List
from rich import print
from urllib.parse import urljoin
from fastapi import APIRouter, HTTPException, Path, Query, Request
from starlette import status
from starlette.responses import Response

from sportscanner.api.routers.geolocation.schemas import PostcodesResponseModel
from sportscanner.api.routers.geolocation.utils import *
from sportscanner.api.routers.venues.utils import get_venues_near_postcode, get_venues_from_database, get_venue_by_composite_key
from sportscanner.api.responses import json_response
from sportscanner.cache import get_or_load_json
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.variables import *
from sportscanner.api.routers.core.schemas import *
import sportscanner.storage.postgres.database as db

router = APIRouter()

# Venue metadata only changes when a venue is added, but these endpoints used to
# re-read the whole table and rebuild one Pydantic model per venue on every
# request (771 rows, about 1.5s cold). Cache the serialised list, and let
# browsers and the CDN hold it briefly too.
VENUES_LIST_CACHE_KEY = "venues_list:v1"
VENUES_LIST_TTL_SECONDS = 300
_VENUES_CACHE_HEADER = "public, max-age=300, stale-while-revalidate=600"


def _venue_payload(venue: SportsVenue) -> dict:
    """The exact shape of SportVenueOutputModel, as a plain dict."""
    return {
        "composite_key": venue.composite_key,
        "venue_name": venue.venue_name,
        "address": venue.address,
        "sports": venue.sports,
        "latitude": venue.latitude,
        "longitude": venue.longitude,
    }


def _venue_list_response(
    rows: List[dict], limit: Optional[int], request: Request
) -> Response:
    body = rows[:limit] if limit is not None else rows
    return json_response(body, request, _VENUES_CACHE_HEADER)


@router.get("/") # /venues/?limit=10
def get_all_venues(
    request: Request,
    limit: Optional[int] = Query(None, description="Limit the number of venues in the response"),
) -> List[SportVenueOutputModel]:
    """Get all Sports Venues"""
    rows = get_or_load_json(
        f"{VENUES_LIST_CACHE_KEY}:all",
        lambda: [_venue_payload(v) for v in get_venues_from_database(limit=None)],
        VENUES_LIST_TTL_SECONDS,
    )
    return _venue_list_response(rows, limit, request)

@router.get("/sports/{sport}") # /venues/sports/{sport}?limit=10
def get_venues_offering_sport(
    request: Request,
    sport: SportscannerSupportedSports = Path(..., description="Supported sport to filter venues"),
    limit: Optional[int] = Query(None, description="Optional paramter: Limits the number of venues in the response"),
) -> List[SportVenueOutputModel] :
    """Get all Sports Venues offering a specific sport"""
    rows = get_or_load_json(
        f"{VENUES_LIST_CACHE_KEY}:{sport.value}",
        lambda: [
            _venue_payload(v)
            for v in get_venues_from_database(sports=[sport.value], limit=None)
        ],
        VENUES_LIST_TTL_SECONDS,
    )
    return _venue_list_response(rows, limit, request)


@router.get("/near") # /venues/near?postcode=SE17TP&distance=5.0
async def venues_near_postcode_and_radius(
    postcode: str = Query(..., description="Raw postcode to find nearby venues"),
    distance: Optional[float] = Query(
        10.0, description="Fetch venues within defined radius (in miles)"
    ),
) -> List[VenueDistanceModel]:
    """Get metadata associated with postcode"""
    try:
        return await get_venues_near_postcode(postcode, distance)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{composite_key}") # /venues/{composite}
def get_venue_info(
    composite_key: str = Path(
        description="Composite key identifier to fetch venue information"
    ),
) -> List[SportVenueOutputModel]:
    sports_venues: List[SportsVenue] = get_venue_by_composite_key(composite_key=composite_key)
    output: List[SportVenueOutputModel] = [
        SportVenueOutputModel(
            composite_key=venue.composite_key,
            venue_name=venue.venue_name,
            address=venue.address,
            sports=venue.sports,
            latitude=venue.latitude,
            longitude=venue.longitude,
        ) for venue in sports_venues
    ]
    return output


