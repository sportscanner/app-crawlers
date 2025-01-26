from enum import Enum
from typing import List, Optional

from pydantic import UUID4, BaseModel, RootModel


class Location(BaseModel):
    """Location metadata, important for nearby slots searches"""

    postcode: Optional[str] = None
    address: Optional[str] = None
    latitude: float
    longitude: float


class Venue(BaseModel):
    venue_name: str
    slug: str
    location: Location


class Organisation(BaseModel):
    organisation: str
    organisation_website: str
    venues: List[Venue]


class SportsVenueMappingModel(RootModel):
    root: List[Organisation]
