from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from sportscanner.storage.postgres.tables import GameParticipantStatus, GameStatus


class GameCreate(BaseModel):
    venue_name: str
    sport: str
    scheduled_at: datetime
    duration_minutes: Optional[int] = None
    capacity: int
    price_pence: int  # amount each joining participant pays, in pence
    notes: Optional[str] = None


class ParticipantOut(BaseModel):
    id: str
    user_id: str
    display_name: str
    status: GameParticipantStatus
    amount_pence: int
    joined_at: datetime


class GameOut(BaseModel):
    id: str
    organizer_id: str
    organizer_name: str
    venue_name: str
    sport: str
    scheduled_at: datetime
    duration_minutes: Optional[int]
    capacity: int
    spots_remaining: int
    price_pence: int
    currency: str
    platform_fee_percent: float
    platform_fee_fixed_pence: int
    status: GameStatus
    notes: Optional[str]
    participants: list[ParticipantOut]
    created_at: datetime


class GameListOut(BaseModel):
    id: str
    organizer_name: str
    venue_name: str
    sport: str
    scheduled_at: datetime
    capacity: int
    spots_remaining: int
    price_pence: int
    currency: str
    status: GameStatus


class JoinGameOut(BaseModel):
    client_secret: str
    payment_intent_id: str
    amount_pence: int
    platform_fee_pence: int
