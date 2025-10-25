from datetime import datetime
from typing import List
from rich import print
from urllib.parse import urljoin
import httpx
from fastapi import APIRouter, Path, Query
from sqlmodel import text

from sportscanner.api.routers.geolocation.schemas import PostcodesResponseModel
from sportscanner.api.routers.geolocation.utils import *
from sportscanner.api.routers.venues.utils import build_geodistance_text_clause, get_venues_from_database, get_venue_by_composite_key
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
            venue=venue.venue_name,
            address=venue.address,
            sports=venue.sports,
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
        sports=[sport.name], 
        limit=limit
    )
    
    output: List[SportVenueOutputModel] = [
        SportVenueOutputModel(
            composite_key=venue.composite_key,
            venue=venue.venue_name,
            address=venue.address,
            sports=venue.sports,
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
    async with httpx.AsyncClient() as client:
        geolocation_api_url = f"https://api.postcodes.io/postcodes/{postcode}"
        logging.info("Requesting:", geolocation_api_url)
        response = await client.get(geolocation_api_url)
    
    search_postcode_metadata: PostcodeAPIResponse = PostcodeAPIResponse(
        **response.json()
    )

    clause = build_geodistance_text_clause(
        search_postcode_metadata.result.longitude,
        search_postcode_metadata.result.latitude,
        miles=distance
    ).params(
        lon=search_postcode_metadata.result.longitude,
        lat=search_postcode_metadata.result.latitude,
        meters=distance * 1609.34
    )

    clause: str = f"""
        SELECT
            composite_key,
            venue_name,
            ROUND((ST_Distance(
                srid,
                ST_SetSRID(ST_MakePoint({search_postcode_metadata.result.longitude}, {search_postcode_metadata.result.latitude}), 4326)::geography
            ) / 1609.344)::numeric, 1) AS distance_miles,
            address,
            sports
        FROM
            sportsvenue
        WHERE
            ST_DWithin(
                srid,
                ST_SetSRID(ST_MakePoint({search_postcode_metadata.result.longitude}, {search_postcode_metadata.result.latitude}), 4326)::geography,
                {distance} * 1609.344
            )
        ORDER BY
            ST_Distance(
                srid,
                ST_SetSRID(ST_MakePoint({search_postcode_metadata.result.longitude}, {search_postcode_metadata.result.latitude}), 4326)::geography
            )
        """
    
    rows= db.get_all_rows(
        db.engine, 
        SportsVenue, 
        text(clause)
    )
    results: List[VenueDistanceModel] = [
        VenueDistanceModel(
            composite_key=row.composite_key,
            venue_name=row.venue_name,
            distance=row.distance_miles,
            address=row.address,
            sports=row.sports
        )
        for row in rows
    ]
    return results


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
            venue=venue.venue_name,
            address=venue.address,
            sports=venue.sports,
        ) for venue in sports_venues
    ]
    return output


