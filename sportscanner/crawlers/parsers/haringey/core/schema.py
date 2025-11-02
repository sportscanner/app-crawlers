"""Contains dataclasses for the API call schema"""

from pydantic import BaseModel


class TimeFormat(BaseModel):
    format_12_hour: str
    format_24_hour: str


class Price(BaseModel):
    formatted_amount: str


class HaringeyApiResponseSchema(BaseModel):
    starts_at: TimeFormat
    ends_at: TimeFormat
    duration: str
    price: Price
    category_slug: str
    date: str
    venue_slug: str
    spaces: int
    name: str
