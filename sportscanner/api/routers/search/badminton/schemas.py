from typing import List, Optional
from datetime import datetime, date, time
from pydantic import BaseModel

class AnalyticsCriteria(BaseModel):
    ...

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
    consecutiveSlots: int = None
    allLocations: bool = True
    radius: float
    analytics: Optional[AnalyticsCriteria] = None
