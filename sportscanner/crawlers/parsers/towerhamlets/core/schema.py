from datetime import date, datetime, time
from typing import List, Optional

from pydantic import BaseModel, Field


class LocationDetails(BaseModel):
    locationId: str
    locationName: str


class Availability(BaseModel):
    inCentre: int
    virtual: int


class SlotReferences(BaseModel):
    inCentre: Optional[str]
    virtual: Optional[str]


class Slot(BaseModel):
    startTime: str
    endTime: str
    bookableFrom: str
    bookableUntil: str
    availability: Availability
    alertListEnabled: bool
    alertListCount: int
    status: str
    slotReferences: SlotReferences


class Location(BaseModel):
    locationNameToDisplay: str
    locationDetails: List[LocationDetails]
    slots: List[Slot]


class Capacity(BaseModel):
    maxInCentreBookees: int
    maxVirtualBookees: int


class GroupActivityDetails(BaseModel):
    isGroupActivity: bool
    priceLevels: List


class TowerHamletsResponseSchema(BaseModel):
    activityGroupId: str
    activityGroupDescription: str
    id: str
    name: str
    description: str
    date: str
    imageUrl: Optional[str] = None
    inCentre: bool
    virtual: bool
    siteId: str
    webBookable: bool
    webComments: str
    capacity: Capacity
    typeInd: str
    slotCount: int
    groupActivityDetails: GroupActivityDetails
    locations: List[Location]


class AggregatedTowerHamletsResponse(BaseModel):
    date: date
    starting_time: time
    ending_time: time
    spaces: int
