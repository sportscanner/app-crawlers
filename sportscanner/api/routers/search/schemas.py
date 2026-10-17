from datetime import date, datetime, time
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


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
    model_config = ConfigDict(json_schema_extra={
        "examples": [{
            "postcode": "SE1 8UL",
            "timeRange": {"starting": "18:00", "ending": "22:00"},
            "radius": 3,
            "sortBy": "distance",
            "analytics": {
                "consecutiveSlots": None,
                "searchUserPreferredLocations": False,
                "specifiedVenues": None,
            },
            "indoor": None,
        }],
    })
    postcode: Optional[str] = None
    timeRange: Optional[TimeFilter] = None
    radius: Optional[float] = None
    analytics: Optional[AdvancedFiltersCriteria] = None
    sortBy: Optional[SortByOptions] = "distance" # 2 options: distance/price
    # True/False to filter to indoor/outdoor courts only (padel/tennis/pickleball
    # tables only - see UnifiedParserSchema.indoor). None (default) = no filter,
    # returns indoor, outdoor, and unknown-status slots together.
    indoor: Optional[bool] = None
