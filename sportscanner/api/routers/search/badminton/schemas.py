from datetime import date, datetime, time
from typing import List, Optional

from pydantic import BaseModel


class AnalyticsCriteria(BaseModel):
    consecutiveSlots: Optional[int] = None
    searchUserPreferredLocations: Optional[bool] = False


class DateFilter(BaseModel):
    starting: date
    ending: date


class TimeFilter(BaseModel):
    starting: time
    ending: time


class SearchCriteria(BaseModel):
    postcode: str
    sport: str
    dateRange: DateFilter
    timeRange: TimeFilter
    radius: float
    analytics: Optional[AnalyticsCriteria] = None
