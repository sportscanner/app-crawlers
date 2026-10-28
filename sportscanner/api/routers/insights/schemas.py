"""Public contracts for point-in-time price and supply reports."""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel

from sportscanner.api.routers.core.schemas import SportscannerSupportedSports


class PriceIndexPoint(BaseModel):
    date: date
    index: Optional[float]
    matched_samples: int
    matched_venues: int


class VenuePriceChange(BaseModel):
    composite_key: str
    venue_name: str
    before: float
    after: float
    change_percent: Optional[float]
    matched_samples: int


class PriceHistory(BaseModel):
    baseline: Optional[date]
    latest: Optional[date]
    observed_days: int
    change_percent: Optional[float]
    series: List[PriceIndexPoint]
    venues: List[VenuePriceChange]


class SupplyPoint(BaseModel):
    date: date
    venues: int
    courts: int


class HistoricalReport(BaseModel):
    sport: SportscannerSupportedSports
    generated_at: datetime
    prices: PriceHistory
    supply: List[SupplyPoint]
