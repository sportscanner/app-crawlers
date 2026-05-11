from pydantic import BaseModel
from typing import List


class MatchiSlot(BaseModel):
    """Represents a single bookable time block for one or more courts at a Matchi facility."""
    facility_id: str
    facility_name: str
    facility_slug: str
    start_timestamp_ms: int  # Unix ms, UTC
    end_timestamp_ms: int    # Unix ms, UTC; sourced from the booking href
    slot_ids: List[str]      # One per bookable court
    duration_minutes: int


class MatchiPriceItem(BaseModel):
    slot_id: str
    currency: str
    price: float
    facility_country_code: str
