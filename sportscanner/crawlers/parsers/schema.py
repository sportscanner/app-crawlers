"""Contains dataclasses for the API call schema"""

from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel

from sportscanner.crawlers.parsers.better.schema import BetterApiResponseSchema
from sportscanner.crawlers.parsers.citysports.schema import CitySportsResponseSchema


class SportsVenue(BaseModel):
    composite_key: str
    organisation: str
    organisation_website: str
    venue_name: str
    slug: str
    postcode: str
    latitude: float
    longitude: float


class UnifiedParserSchema(BaseModel):
    category: str
    starting_time: time
    ending_time: time
    date: date
    price: str
    spaces: int
    composite_key: str
    last_refreshed: datetime
    booking_url: Optional[str]

    @classmethod
    def from_better_api_response(
        cls, response: BetterApiResponseSchema, metadata: SportsVenue
    ):
        return cls(
            category=response.name,
            starting_time=datetime.strptime(
                response.starts_at.format_24_hour, "%H:%M"
            ).time(),
            ending_time=datetime.strptime(
                response.ends_at.format_24_hour, "%H:%M"
            ).time(),
            date=datetime.strptime(response.date, "%Y-%m-%d").date(),
            price=response.price.formatted_amount,
            spaces=response.spaces,
            composite_key=metadata.composite_key,
            last_refreshed=datetime.now(),
            booking_url="https://bookings.better.org.uk/location/{}/{}/{}/by-time/".format(
                response.venue_slug,
                response.category_slug,
                datetime.strptime(response.date, "%Y-%m-%d").date(),
            ),
        )

    @classmethod
    def from_citysports_api_response(
        cls, response: CitySportsResponseSchema, metadata: SportsVenue
    ):
        return cls(
            category=response.ActivityGroupDescription,
            starting_time=datetime.strptime(
                response.StartTime, "%Y-%m-%dT%H:%M:%S"
            ).time(),
            ending_time=datetime.strptime(response.EndTime, "%Y-%m-%dT%H:%M:%S").time(),
            date=datetime.strptime(response.StartTime, "%Y-%m-%dT%H:%M:%S").date(),
            price="£" + str(response.Price),
            spaces=response.AvailablePlaces,
            composite_key=metadata.composite_key,
            last_refreshed=datetime.now(),
            booking_url="https://bookings.citysport.org.uk/LhWeb/en/Public/Bookings/",
        )
