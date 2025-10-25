import json
from typing import Annotated, List, Literal, Optional

from sportscanner.logger import logging
from pydantic import Field, ValidationError

import sportscanner.storage.postgres.database as db
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner import config
from enum import Enum
from typing import Tuple
from pydantic import BaseModel
from sportscanner.api.routers.geolocation.utils import *
from dataclasses import dataclass
from sqlalchemy import text, bindparam
from typing import Optional, Sequence
from sportscanner.api.routers.core.schemas import *

def get_venues_from_database(
        sports: Annotated[List[Literal["badminton", "pickleball", "squash"]], Field(description="Sport category to filter venues")] = ["badminton", "pickleball", "squash"], 
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


def build_geodistance_text_clause(
    longitude: float,
    latitude: float,
    miles: float = 5.0,
    table_name: str = "sportsvenue",
) -> text:
    """Builds a parameterized SQL TextClause that finds venues within `miles` miles of a point.

    Returns a SQLAlchemy TextClause with bound parameters (lon, lat, meters, limit) so it can be
    passed to `get_all_rows(engine, SportsVenue, expression)` directly.

    Example usage:
        clause = build_geodistance_text_clause(-0.03837, 51.502283, miles=5.0, limit=10)
        rows = get_all_rows(engine, SportsVenue, clause)

    Notes:
        - This assumes your table has a `geog_point` geography column (PostGIS) and a `venue_name` column.
        - The function precomputes meters = miles * 1609.344 and binds it as a parameter.
    """

    meters = float(miles) * 1609.344

    sql = f"""
    SELECT
        venue_name,
        ST_Distance(
            geog_point,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
        ) / 1609.344 AS distance_miles
    FROM
        {table_name}
    WHERE
        ST_DWithin(
            geog_point,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            :meters
        )
    ORDER BY
        distance_miles
    """

    clause = text(sql).bindparams(
        bindparam("lon", type_=float),
        bindparam("lat", type_=float),
        bindparam("meters", type_=float),
    )

    # attach actual parameter values so calling code can pass clause directly to session.exec
    return clause