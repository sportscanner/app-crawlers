from pydantic import BaseModel
from typing import List


class PlaytomicSlot(BaseModel):
    start_time: str  # "HH:MM:SS" in local venue time
    duration: int    # minutes
    price: str       # e.g. "68 GBP"


class PlaytomicResource(BaseModel):
    """A single bookable court and its available time slots for a given date."""
    resource_id: str
    start_date: str
    slots: List[PlaytomicSlot] = []
