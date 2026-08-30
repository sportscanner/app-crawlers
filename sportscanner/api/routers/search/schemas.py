from datetime import date, datetime, time
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class AdvancedFiltersCriteria(BaseModel):
    consecutiveSlots: Optional[int] = None
    searchUserPreferredLocations: Optional[bool] = False
    specifiedVenues: Optional[List[str]] = None


class TimeFilter(BaseModel):
    starting: time
    ending: time


class SortByOptions(Enum):
    distance = "distance"
    price = "price"

class SearchCriteria(BaseModel):
    postcode: Optional[str] = None
    timeRange: Optional[TimeFilter] = None
    radius: Optional[float] = None
    analytics: Optional[AdvancedFiltersCriteria] = None
    sortBy: Optional[SortByOptions] = "distance" # 2 options: distance/price
    # True/False to filter to indoor/outdoor courts only (padel/tennis/pickleball
    # tables only - see UnifiedParserSchema.indoor). None (default) = no filter,
    # returns indoor, outdoor, and unknown-status slots together.
    indoor: Optional[bool] = None
