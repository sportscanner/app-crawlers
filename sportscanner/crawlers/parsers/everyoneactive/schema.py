"""Contains dataclasses for the API call schema"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime, date, time

from sportscanner.crawlers.parsers.everyoneactive.dateformatter import convert_sUTC_to_datetime


class Slot(BaseModel):
    datetimeUTC: int = Field(..., alias="sUTC")
    parsedDate: date = None
    parsedStartTime: time = None
    parsedEndTime: time = None
    p: str
    pd: Optional[str]
    rp: bool
    availableSlots: int = Field(..., alias="s")


class BookableItem(BaseModel):
    courtName: str = Field(..., alias="n")
    courtId: str = Field(..., alias="id")
    slots: List[Slot]

class EveryoneActiveRawSchema(BaseModel):
    apiVer: str = Field(..., alias="apiVer")
    globalInfo: Optional[dict]
    siteTimezone: str
    maxBookableTime: int
    frequency: int
    duration: int
    addonOptionsAvailable: bool
    bookableItems: List[BookableItem]


class SlotAvailability(BaseModel):
    slot_date: date
    start_time: time
    end_time: time
    available_slots: int

class AggregatedAvailabilityResponse(BaseModel):
    slots: List[SlotAvailability]
