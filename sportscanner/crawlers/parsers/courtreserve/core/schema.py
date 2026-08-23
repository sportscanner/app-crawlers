"""Response schema for CourtReserve's public Session Calendar endpoint
(/Online/Calendar/ReadCalendarEvents/{orgId}).

The Kendo MVC scheduler transport wraps rows as {Data: [...], Total: int}.
Each row is a single dated occurrence of a recurring session (event series);
the venue name is embedded in the Title/EventName string ("Social Play -
Hampstead"), there is no separate venue field. Availability comes from
MaxMembersOnEvent/SignedMembers/IsFull rather than a court-slot list.
"""

from typing import Optional

from pydantic import BaseModel


class CourtReserveCalendarEventSchema(BaseModel):
    """Only the fields the parser consumes are typed; the real payload carries
    ~60 keys (waitlist flags, league fields, styling colours) that are ignored."""

    Title: str
    EventName: str
    EventType: Optional[str] = None
    Number: str  # unique per occurrence, used in the public booking URL path
    Start: str  # "/Date(1787470200000)/" epoch millis, UTC
    End: str
    MaxMembersOnEvent: int
    SignedMembers: int
    IsFull: bool
    InPast: bool
    TimeDisplay: Optional[str] = None  # "08:30 - 10:00", Europe/London local
    SlotsInfo: Optional[str] = None  # "4 of 10 spots remaining"
