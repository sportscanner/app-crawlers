from enum import Enum
from typing import List, Optional

from pydantic import UUID4, BaseModel

MAPPINGS = "sportscanner/mappings.json"

from enum import Enum
from uuid import UUID


class Location(BaseModel):
    """Location metadata, important for nearby slots searches"""

    postcode: str
    latitude: float
    longitude: float


class SportsVenueMappingSchema(BaseModel):
    """Sports centre list of locations"""

    venue_name: str
    slug: str
    organisation_name: Optional[str]
    organisation_hash: Optional[str]
    parser_uuid: UUID4
    location: Location


class Venue(BaseModel):
    venue_name: str
    slug: str
    location: Location


class Organisation(BaseModel):
    organisation: str
    organisation_website: str
    venues: List[Venue]



