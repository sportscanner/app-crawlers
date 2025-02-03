from datetime import date, datetime, time
from typing import List, Optional

from pydantic import BaseModel


class AnalyticsCriteria(BaseModel):
    consecutiveSlots: Optional[int] = None
    searchUserPreferredLocations: Optional[bool] = False


class TimeFilter(BaseModel):
    starting: time
    ending: time


class SearchCriteria(BaseModel):
    postcode: str
    sport: str
    dates: List[date]
    timeRange: TimeFilter
    radius: float
    analytics: Optional[AnalyticsCriteria] = None
