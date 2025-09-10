from pydantic import BaseModel, RootModel
from typing import List, Optional
from datetime import datetime

# ... (Your existing Offer and Activity schemas) ...

class Offer(BaseModel):
    identifier: str
    currency: str
    price: float
    name: str
    description: Optional[str] = None

class Activity(BaseModel):
    identifier: str
    activityIdentifier: str
    childId: str
    remainingAttendeeCapacity: int
    maximumAttendeeCapacity: int
    bookableUntilTheEnd: bool
    startDate: datetime
    endDate: datetime
    status: str
    offers: List[Offer]
    tenantName: str
    liveUrl: Optional[str] = None # Or HttpUrl if you want validation
    noteForAttendees: Optional[str] = None
    meta: Optional[dict] = None

# This is the crucial part: use RootModel to handle the list.
class DecathlonRawSchema(RootModel):
    root: List[Activity]