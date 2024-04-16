"""Contains dataclasses for the API call schema"""

from pydantic import BaseModel
from datetime import datetime, time, date
from typing import Optional
from shuttlebot.backend.parsers.better.schema import BetterApiResponseSchema
from shuttlebot.backend.parsers.citysports.schema import CitySportsResponseSchema

class UnifiedParserSchema(BaseModel):
    name: Optional[str]
    venue_slug: Optional[str]
    category: str
    starting_time: time
    ending_time: time
    date: date
    price: str
    spaces: int
    organisation: str
    last_refreshed: datetime
    booking_url: Optional[str]

    @classmethod
    def from_better_api_response(cls, response: BetterApiResponseSchema):
        return cls(
            name=None,
            venue_slug=response.venue_slug,
            category=response.name,
            starting_time=datetime.strptime(response.starts_at.format_24_hour,
                                            "%H:%M").time(),
            ending_time=datetime.strptime(response.ends_at.format_24_hour,
                                            "%H:%M").time(),
            date=datetime.strptime(response.date,"%Y-%m-%d").date(),
            price=response.price.formatted_amount,
            spaces=response.spaces,
            organisation="better.org.uk",
            last_refreshed=datetime.now(),
            booking_url=f"""
            https://bookings.better.org.uk/location/{response.venue_slug}/{response.category_slug}/
                {datetime.strptime(response.date,"%Y-%m-%d").date()}/by-time/
            """
        )

    @classmethod
    def from_citysports_api_response(cls, response: CitySportsResponseSchema):
        return cls(
            name="CitySports Leisure Hub",
            venue_slug="citysport",
            category=response.ActivityGroupDescription,
            starting_time=datetime.strptime(response.StartTime, '%Y-%m-%dT%H:%M:%S').time(),
            ending_time=datetime.strptime(response.EndTime, '%Y-%m-%dT%H:%M:%S').time(),
            date=datetime.strptime(response.StartTime, '%Y-%m-%dT%H:%M:%S').date(),
            price="£" + str(response.Price),
            spaces=response.AvailablePlaces,
            organisation="citysport.org.uk",
            last_refreshed=datetime.now(),
            booking_url=None
        )
