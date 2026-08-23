"""Gladstone Go availability API response shapes (Mytime Active tenant)."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class GladstoneGoAvailability(BaseModel):
    inCentre: int = 0
    virtual: int = 0


class GladstoneGoSlot(BaseModel):
    startTime: datetime
    endTime: datetime
    availability: GladstoneGoAvailability
    status: Optional[str] = None


class GladstoneGoLocation(BaseModel):
    locationNameToDisplay: Optional[str] = None
    slots: List[GladstoneGoSlot] = []


class GladstoneGoSessionSchema(BaseModel):
    """One session block per (activity, date) as returned by
    /api/availability/V2/sessions. Courts are nested under `locations`, each
    carrying its own slot list."""

    id: str
    name: Optional[str] = None
    date: str
    siteId: str
    webBookable: bool = False
    slotCount: int = 0
    locations: List[GladstoneGoLocation] = []
