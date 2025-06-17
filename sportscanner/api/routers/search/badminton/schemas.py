from datetime import date, datetime, time
from typing import List, Optional

from pydantic import BaseModel


class AdvancedFiltersCriteria(BaseModel):
    consecutiveSlots: Optional[int] = None
    searchUserPreferredLocations: Optional[bool] = False
    specifiedVenues: Optional[List[str]] = None


class TimeFilter(BaseModel):
    starting: time
    ending: time


class SearchCriteria(BaseModel):
    postcode: str
    sport: Optional[str] = None
    dates: List[date]
    timeRange: TimeFilter
    radius: float
    analytics: Optional[AdvancedFiltersCriteria] = None
    sortBy: Optional[str] = "distance" # 2 options: distance/price
