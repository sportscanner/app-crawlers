from datetime import date, datetime, time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator


class BusinessSportKind(str, Enum):
    badminton = "badminton"
    squash = "squash"
    pickleball = "pickleball"


class PartnerOnboardRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    website: HttpUrl
    email: EmailStr
    password: str = Field(min_length=8, max_length=120)


class PartnerLoginRequest(BaseModel):
    email: EmailStr
    password: str


class PartnerProfile(BaseModel):
    id: str
    name: str
    website: str
    email: str
    status: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    partner: PartnerProfile


class OnboardResponse(AuthResponse):
    initial_api_key: str


class ApiKeyCreateRequest(BaseModel):
    label: str = Field(min_length=2, max_length=80)


class ApiKeyCreateResponse(BaseModel):
    id: str
    label: str
    key_prefix: str
    api_key: str


class ApiKeyResponse(BaseModel):
    id: str
    label: str
    key_prefix: str
    active: bool
    created_at: datetime
    last_used_at: Optional[datetime]


class VenueCreateRequest(BaseModel):
    venue_name: str = Field(min_length=2, max_length=180)
    organisation: Optional[str] = Field(default=None, max_length=180)
    organisation_website: Optional[HttpUrl] = None
    slug: Optional[str] = Field(default=None, max_length=200)
    postcode: Optional[str] = Field(default=None, max_length=16)
    address: Optional[str] = Field(default=None, max_length=280)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    sports: list[BusinessSportKind] = Field(default_factory=list, min_length=1)


class VenueResponse(BaseModel):
    composite_key: str
    venue_name: str
    organisation: str
    organisation_website: str
    slug: str
    postcode: Optional[str]
    address: Optional[str]
    latitude: float
    longitude: float
    sports: list[str]


class SlotPayload(BaseModel):
    date: date
    starting_time: time
    ending_time: time
    price: str = Field(default="0")
    spaces: int = Field(default=0, ge=0, le=20)
    category: Optional[str] = Field(default=None, max_length=80)
    booking_url: Optional[HttpUrl] = None

    @field_validator("ending_time")
    @classmethod
    def validate_times(cls, ending: time, values):
        starting = values.data.get("starting_time")
        if starting and ending <= starting:
            raise ValueError("ending_time must be after starting_time")
        return ending


class AvailabilityUpsertRequest(BaseModel):
    composite_key: str = Field(min_length=8, max_length=32)
    sport: BusinessSportKind
    source: str = Field(default="portal", max_length=60)
    request_id: Optional[str] = Field(default=None, max_length=120)
    slots: list[SlotPayload] = Field(min_length=1, max_length=400)


class AvailabilityUpsertResponse(BaseModel):
    composite_key: str
    sport: BusinessSportKind
    slots_received: int
    slots_written: int


class DashboardSummaryResponse(BaseModel):
    venues: int
    api_keys: int
    events_24h: int
    slots_24h: int


class VenueCalendarSlotResponse(BaseModel):
    uid: str
    sport: BusinessSportKind
    composite_key: str
    date: date
    starting_time: time
    ending_time: time
    category: str
    price: str
    spaces: int
    booking_url: Optional[str]
    status: str
    last_refreshed: datetime


class SlotDeleteResponse(BaseModel):
    uid: str
    deleted: bool = True
