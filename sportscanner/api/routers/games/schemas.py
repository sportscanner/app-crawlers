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


class ParticipantPublicOut(BaseModel):
    """What anyone browsing a game is allowed to see about a participant —
    no raw Kinde user_id, no payment amount, and display_name never falls
    back to a real email address (see gameService._display_name)."""

    id: str
    display_name: str
    status: GameParticipantStatus
    joined_at: datetime


class ParticipantOut(ParticipantPublicOut):
    """Organizer-only view of a participant (returned via GET /games/mine),
    with the fields needed to manage payouts/disputes."""

    user_id: str
    amount_pence: int


class GameDetailOut(BaseModel):
    """Public-facing game detail — GET /games/{id}. Deliberately omits
    organizer_id (internal Kinde ID) and per-participant user_id/amount_pence."""

    id: str
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
    participants: list[ParticipantPublicOut]
    created_at: datetime
    is_organizer: bool  # true only when the (optionally) authenticated caller is the organizer —
    # lets the frontend show the right actions (e.g. "Cancel game") without ever exposing organizer_id


class GameOut(BaseModel):
    """Organizer-only full view — GET /games/mine, POST /games/. Includes
    organizer_id and the full per-participant ParticipantOut."""

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


class CancelGameOut(BaseModel):
    refunded_count: int
    failed_participant_ids: list[str]  # non-empty means those refunds need manual follow-up in Stripe
