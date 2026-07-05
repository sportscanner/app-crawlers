from datetime import datetime
from typing import List
from rich import print
from urllib.parse import urljoin
from fastapi import APIRouter, HTTPException, Path, Query
from starlette import status

from sportscanner.api.routers.geolocation.schemas import PostcodesResponseModel
from sportscanner.api.routers.geolocation.utils import *
from sportscanner.api.routers.venues.utils import get_venues_near_postcode, get_venues_from_database, get_venue_by_composite_key
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.variables import *
from sportscanner.api.routers.core.schemas import *
import sportscanner.storage.postgres.database as db

router = APIRouter()


@router.get("/") # /venues/?limit=10
async def get_all_venues(
    limit: Optional[int] = Query(None, description="Limit the number of venues in the response"),
) -> List[SportVenueOutputModel]:
    """Get all Sports Venues"""
    sports_venues: List[SportsVenue] = get_venues_from_database(limit=limit)
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

@router.get("/sports/{sport}") # /venues/sports/{sport}?limit=10
async def get_venues_offering_sport(
    sport: SportscannerSupportedSports = Path(..., description="Supported sport to filter venues"),
    limit: Optional[int] = Query(None, description="Optional paramter: Limits the number of venues in the response"),
) -> List[SportVenueOutputModel] :
    """Get all Sports Venues offering a specific sport"""
    sports_venues: List[SportsVenue] = get_venues_from_database(
        sports=[sport.value],
        limit=limit
    )

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
async def get_venue_info(
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


