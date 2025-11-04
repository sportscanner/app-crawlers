from typing import Optional
from pydantic import BaseModel, computed_field
from datetime import date, datetime, timedelta

class VenueAvailability(BaseModel):
    venue_name: str
    date: Optional[date]
    latest_refresh: Optional[datetime]

    @computed_field
    @property
    def health(self) -> str:
        """Return 'ok' if latest_refresh is within the last hour, else 'deprecated'."""
        if self.latest_refresh is None:
            return "deprecated"
        if datetime.utcnow() - self.latest_refresh > timedelta(minutes=35):
            return "deprecated"
        return "ok"