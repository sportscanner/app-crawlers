from enum import Enum
from typing import List, Optional

from pydantic import UUID4, BaseModel

START_TIME, END_TIME = "17:30", "22:00"
MAPPINGS = "mappings.json"

from enum import Enum
from uuid import UUID


class Parsers(Enum):
    better = UUID("5184145c-4d83-4e3b-8bed-3466331a45ba")
    schoolhire = UUID("331b6c8a-ef34-4633-82d9-9b13852117ca")


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
