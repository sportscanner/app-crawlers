from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PadelMatesSlot(BaseModel):
    """One entry of the `allSlots` array from
    /player/player_booking/all_courts_slot_prices_v2. Only a subset of the
    fields the API returns is needed; unknown fields are ignored."""

    courtName: str
    courtId: str
    slotId: Optional[str] = None
    duration: int  # minutes (60 / 90 / 120 observed)
    price: float
    startDatetime: datetime  # ISO 8601 with +00:00 offset (UTC)
    endDatetime: datetime
    startTime: Optional[str] = None  # "HH:MM", UTC clock
    endTime: Optional[str] = None
    reservedIntersection: bool = False
