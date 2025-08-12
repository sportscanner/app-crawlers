from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple, Coroutine, Optional
from datetime import date, datetime, time
import httpx
from pydantic import BaseModel

from sportscanner.storage.postgres.tables import SportsVenue


class AdditionalRequestMetadata(BaseModel):
    category: str
    date: date
    price: Optional[str] = None # can be pre-defined, or extracted from response
    last_refreshed: Optional[datetime] = datetime.now()
    booking_url: Optional[str] = None # can be pre-defined, or extracted from response
    sportsCentre: SportsVenue


class RequestDetailsWithMetadata(BaseModel):
    url: str
    headers: Dict[str, Any]
    payload: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
    cookies: Optional[str] = None,
    metadata: Optional[AdditionalRequestMetadata] = None # To carry over any specific context

class RawResponseData(BaseModel): # Example, adjust as needed
    content: Any
    status_code: int
    headers: Dict[str, str]
    requestMetadata: RequestDetailsWithMetadata


class SportsVenue(BaseModel):
    composite_key: str
    organisation: str
    organisation_website: str
    venue_name: str
    slug: str
    postcode: str
    latitude: float
    longitude: float


class UnifiedParserSchema(BaseModel):
    category: str
    starting_time: time
    ending_time: time
    date: date
    price: str
    spaces: int
    composite_key: str
    last_refreshed: datetime
    booking_url: Optional[str]