from typing import List, Optional

from pydantic import BaseModel


class ClubSparkSession(BaseModel):
    Category: int
    SubCategory: Optional[int] = None
    Name: str
    StartTime: int  # minutes from midnight
    EndTime: int
    Interval: Optional[int] = None
    Capacity: Optional[int] = None
    # e.g. "Administrator, NTC Front of House" or "Member". Non-empty means
    # the slot is only bookable by those roles and must not be exposed as
    # public availability.
    Restrictions: Optional[str] = None
    Cost: Optional[float] = None
    CostFrom: Optional[float] = None
    CourtCost: Optional[float] = None
    LightingCost: Optional[float] = None
    MemberPrice: Optional[float] = None
    GuestPrice: Optional[float] = None
    Recurrence: Optional[bool] = None


class ClubSparkDay(BaseModel):
    Date: str
    Sessions: List[ClubSparkSession] = []


class ClubSparkResource(BaseModel):
    ID: str
    Name: str
    Category: Optional[int] = None
    # 0 = outdoor, 1 = indoor, 2 = temporary indoor, 99 = other.
    Location: Optional[int] = None
    Days: List[ClubSparkDay] = []


class ClubSparkVenueSessionsResponse(BaseModel):
    TimeZone: Optional[str] = None
    # Venue-wide minimum bookable interval (30 or 60 minutes). The session's
    # own `Interval` is not reliable for this: Old Deer Park returns sessions
    # with Interval=60 while its booking page/HTML splits them into 30-minute
    # intervals at the session's per-interval cost.
    MinimumInterval: Optional[int] = None
    Resources: List[ClubSparkResource] = []
