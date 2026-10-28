from typing import List, Optional

from pydantic import BaseModel


class ClubSparkSession(BaseModel):
    Category: int
    Name: str
    StartTime: int  # minutes from midnight
    EndTime: int
    Interval: Optional[int] = None
    CourtCost: Optional[float] = None


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
    Resources: List[ClubSparkResource] = []
