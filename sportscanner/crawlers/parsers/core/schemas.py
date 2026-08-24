from typing import Any, Dict, List, Optional
from datetime import date, datetime, time
from pydantic import BaseModel, Field

from sportscanner.storage.postgres.tables import SportsVenue


class AdditionalRequestMetadata(BaseModel):
    category: str
    date: Optional[date]
    price: Optional[str] = None # can be pre-defined, or extracted from response
    # default_factory so each request stamps its own fetch time, rather than
    # freezing the module-import timestamp (feeds the "deprecated after 35 min" check).
    last_refreshed: Optional[datetime] = Field(default_factory=datetime.now)
    booking_url: Optional[str] = None # can be pre-defined, or extracted from response
    sportsCentre: SportsVenue


class RequestDetailsWithMetadata(BaseModel):
    url: str
    headers: Dict[str, Any]
    payload: Optional[Dict[str, Any]] = None
    token: Optional[str] = None
    cookies: Optional[str] = None
    metadata: Optional[AdditionalRequestMetadata] = None # To carry over any specific context
    fallback_urls: Optional[List[str]] = None # Tried in order if `url` returns an HTTP error

class RawResponseData(BaseModel): # Example, adjust as needed
    content: Any
    status_code: int
    headers: Dict[str, str]
    requestMetadata: RequestDetailsWithMetadata


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
    # Total bookable capacity of the session, when the provider exposes it
    # (e.g. CourtReserve's MaxMembersOnEvent). None for whole-court providers
    # where "capacity" doesn't apply.
    capacity: Optional[int] = None