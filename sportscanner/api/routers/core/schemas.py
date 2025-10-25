from dataclasses import dataclass
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from sportscanner.storage.postgres.tables import SportsVenue


class SportVenueOutputModel(BaseModel):
    composite_key: str
    venue: str
    address: str
    sports: List[str]


class SportscannerSupportedSports(Enum):
    """Sports categories supported by Sportscanner"""
    BADMINTON = "badminton"
    SQUASH = "squash"
    PICKLEBALL = "pickleball"


@dataclass
class GeoCoordinates:
    longitude: float
    latitude: float


class SportsVenuesNearRadiusResonseModel(BaseModel):
    distance: float
    venue: SportsVenue


class PostcodeResult(BaseModel):
    """
    Represents the detailed geographical and administrative information for a postcode.
    """
    postcode: str
    region: str
    longitude: float
    latitude: float
    northings: int
    eastings: int

# Model for the top-level JSON structure
class PostcodeAPIResponse(BaseModel):
    """
    Represents the full response structure from the Postcode API.
    """
    status: int
    result: Optional[PostcodeResult] = None # The result can sometimes be null/None on failed lookups

class VenueDistanceModel(BaseModel):
    composite_key: str
    venue_name: str
    distance: float
    address: str
    sports: Optional[List[str]] = None