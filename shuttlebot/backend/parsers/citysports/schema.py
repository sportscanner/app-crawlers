from typing import List, Optional

from pydantic import UUID4, BaseModel


class ApplicableFilter(BaseModel):
    Id: UUID4
    DisplayName: str
    Order: int
    TagGroupId: UUID4
    TagGroupName: str
    Enabled: bool


class CitySportsResponseSchema(BaseModel):
    EventType: int
    SiteId: int
    ActivityCode: str
    LocationCode: str
    LocationDescription: str
    PeriodNumber: int
    GroupCode: str
    CourseCode: Optional[str]
    TicketId: int
    TicketPrices: Optional[str]
    TicketActivityId: Optional[str]
    TicketActive: bool
    CourseType: Optional[str]
    Sequence: int
    DisplayName: str
    ActivityGroupId: UUID4
    ActivityGroupDescription: str
    TermsAndConditionsUrl: Optional[str]
    ActivityDescription: str
    StartTime: str
    EndTime: str
    TotalPlaces: int
    AvailablePlaces: int
    AvailablePlaceLocationDescription: str
    AvailablePlacesLocationDescription: str
    UseNotifyMeLists: bool
    UseBookingSequence: bool
    BookableType: int
    ApplicableFilters: List[ApplicableFilter]
    ImageUrl: Optional[str]
    PriceStruct: Optional[str]
    PriceBand: Optional[str]
    Price: float
    SubLocationGroups: Optional[str]
    DurationDescription: str
    StartSales: str
    EndSales: str
    EnableSales: bool
    UntilEndWarningEnabled: bool
    UntilEndWarningText: Optional[str]
    Instructor: Optional[str]


# Example usage:
# activity_data = { ... }  # Your JSON data here
# activity_instance = Activity(**activity_data)
# print(activity_instance)
