import json
import re
from typing import Annotated, List, Literal, Optional

import httpx
from sportscanner.logger import logging
from pydantic import Field, ValidationError

import sportscanner.storage.postgres.database as db
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner import config
from sportscanner.cache import cache_get_json, cache_set_json
from enum import Enum
from typing import Tuple
from pydantic import BaseModel
from sportscanner.api.routers.geolocation.utils import *
from dataclasses import dataclass
from sqlalchemy import text
from typing import Optional, Sequence
from sportscanner.api.routers.core.schemas import *

def get_venues_from_database(
        sports: Annotated[List[Literal["badminton", "pickleball", "squash", "padel"]], Field(description="Sport category to filter venues")] = ["badminton", "pickleball", "squash", "padel"],
        limit: Annotated[int, Field(description="Limit the number of venues in the response")] = 10
    ) -> List[SportsVenue]:
    """This Tool fetches sports venues from the database offering a specific sport."""
    venues: List[SportsVenue] = db.get_all_rows(
        db.engine, 
        SportsVenue, 
        db.select(SportsVenue)
        .where(SportsVenue.sports.overlap(sports))
        .limit(limit)
    )
    return venues

def get_venue_by_composite_key(
        composite_key: Annotated[str, Field(description="Composite key identifier to fetch venue information")]
    ) -> List[SportsVenue]:
    """This Tool fetches a particular sports venue from the database based on its composite key."""
    venues: List[SportsVenue] = db.get_all_rows(
        db.engine, 
        SportsVenue, 
        db.select(SportsVenue)
        .where(SportsVenue.composite_key == composite_key)
    )
    return venues


def get_sports_venues_within_radius(
        longitude: Annotated[float, Field(description="Longitude of the center point")],
        latitude: Annotated[float, Field(description="Latitude of the center point")],
        distance: Annotated[float, Field(description="Radius distance in miles")],
        sport_category: Annotated[List, Field(description="Optional sport category to filter venues on, array elements must be from these options: 'badminton', 'squash', 'pickleball'")] = [],
    ) -> List[SportsVenuesNearRadiusResonseModel]:
    """This Tool fetches venues within a defined radius from a given point and can filter by sport category."""
    venues: List[SportsVenue] = db.get_all_rows(
        db.engine,
        SportsVenue,
        db.select(SportsVenue)
        .where(SportsVenue.sports.contains([sport_category]))
    )
    venues_distance_from_postcode = []
    for sports_venue in venues:
        _dist = calculate_distance_in_miles(
            locationA=(longitude, latitude),
            locationB=(sports_venue.longitude, sports_venue.latitude),
        )
        venues_distance_from_postcode.append(
            {"distance": _dist, "venue": sports_venue}
        )
    venues_distance_from_postcode = sorted(
        venues_distance_from_postcode, key=lambda x: x["distance"]
    )
    venues_within_defined_radius = list(
        filter(lambda x: x["distance"] <= distance, venues_distance_from_postcode)
    )
    return venues_within_defined_radius


def _normalize_postcode_for_cache_key(postcode: str) -> str:
    return re.sub(r"\s+", "", postcode).upper()


async def geocode_postcode(postcode: str) -> "PostcodeAPIResponse":
    """Resolve a UK postcode to lat/lng via postcodes.io, cached (near-static data)."""
    cache_key = f"geocode:{_normalize_postcode_for_cache_key(postcode)}"
    cached = cache_get_json(cache_key)
    if cached is not None:
        return PostcodeAPIResponse(**cached)

    async with httpx.AsyncClient() as client:
        response = await client.get(f"https://api.postcodes.io/postcodes/{postcode}")
    payload = response.json()
    result = PostcodeAPIResponse(**payload)
    cache_set_json(cache_key, payload)
    return result


async def get_venues_near_postcode(postcode: str, distance: float = 10.0) -> List[VenueDistanceModel]:
    """Venues within `distance` miles of `postcode`. Both the geocode lookup and the
    resulting venue list are cached (short TTL) since this is near-static data re-queried
    on every search. Used directly by both GET /venues/near and POST /search/{sport} —
    search calls this in-process rather than looping back over HTTP to its own API.
    """
    venues_cache_key = f"venues_near:{_normalize_postcode_for_cache_key(postcode)}:{distance}"
    cached = cache_get_json(venues_cache_key)
    if cached is not None:
        return [VenueDistanceModel(**row) for row in cached]

    geocoded = await geocode_postcode(postcode)
    if geocoded.result is None:
        raise ValueError(f"{postcode!r} is not a valid UK postcode")
    longitude, latitude = geocoded.result.longitude, geocoded.result.latitude

    clause = text("""
        SELECT
            composite_key,
            venue_name,
            ROUND((ST_Distance(
                srid,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
            ) / 1609.344)::numeric, 1) AS distance_miles,
            address,
            sports,
            latitude,
            longitude
        FROM
            sportsvenue
        WHERE
            ST_DWithin(
                srid,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :meters
            )
        ORDER BY
            ST_Distance(
                srid,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
            )
    """).bindparams(
        lon=longitude,
        lat=latitude,
        meters=distance * 1609.344,
    )
    rows = db.get_all_rows(db.engine, SportsVenue, clause)
    results = [
        VenueDistanceModel(
            composite_key=row.composite_key,
            venue_name=row.venue_name,
            distance=row.distance_miles,
            address=row.address,
            sports=row.sports,
            latitude=row.latitude,
            longitude=row.longitude,
        )
        for row in rows
    ]
    cache_set_json(venues_cache_key, [r.model_dump() for r in results])
    return results