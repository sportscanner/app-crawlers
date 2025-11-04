from typing import Optional
from pydantic import BaseModel, computed_field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

class VenueAvailability(BaseModel):
    venue_name: str
    date: Optional[date]
    latest_refresh: Optional[datetime]

    @computed_field
    @property
    def health(self) -> str:
        """Return 'ok' if latest_refresh is within the last 35 minutes (UK time), else 'deprecated'."""
        if self.latest_refresh is None:
            return "deprecated"

        now_uk = datetime.now(ZoneInfo("Europe/London"))
        latest = self.latest_refresh

        # Make latest_refresh timezone-aware in UK time if it's naive
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=ZoneInfo("Europe/London"))

        if now_uk - latest > timedelta(minutes=35):
            return "deprecated"
        return "ok"