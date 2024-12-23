from enum import Enum
from typing import List, Optional

from pydantic import UUID4, BaseModel

START_TIME, END_TIME = "17:30", "22:00"
LOGGING_LEVEL = "INFO"
MAPPINGS = "mappings.json"

from enum import Enum
from uuid import UUID


class Location(BaseModel):
    """Location metadata, important for nearby slots searches"""

    postcode: str
    latitude: float
    longitude: float


class SportsCentre(BaseModel):
    """Sports centre list of locations"""

    venue_name: str
    slug: str
    organisation_name: Optional[str]
    organisation_hash: Optional[str]
    parser_uuid: UUID4
    location: Location


class Traversals(BaseModel):
    """Sports centre list of locations"""
    venue_name: str
    slug: str
    organisation_name: Optional[str]
    organisation_hash: Optional[str]
    parser_uuid: UUID4
    location: Location
