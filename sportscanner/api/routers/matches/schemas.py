from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from sportscanner.storage.postgres.tables import MatchType


class ScoreIn(BaseModel):
    game_number: int
    team1_score: int
    team2_score: int


class PlayerIn(BaseModel):
    kinde_user_id: str  # frontend sends user ID; email resolved server-side
    display_name: str
    team: int  # 1 or 2


class MatchCreate(BaseModel):
    venue_name: str
    sport: str
    match_type: MatchType
    played_at: datetime
    duration_minutes: Optional[int] = None
    players: list[PlayerIn]
    scores: list[ScoreIn]
    total_cost: Optional[Decimal] = None


class MatchSplit(BaseModel):
    total_cost: Decimal


class ScoreOut(BaseModel):
    id: UUID
    game_number: int
    team1_score: int
    team2_score: int


class PlayerOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    team: int
    is_creator: bool
    splitwise_notified: Optional[bool] = None


class MatchOut(BaseModel):
    id: UUID
    venue_name: str
    sport: str
    match_type: str
    played_at: datetime
    duration_minutes: Optional[int]
    winning_team: Optional[int]
    total_cost: Optional[Decimal]
    status: str
    splitwise_expense_id: Optional[str]
    splitwise_error: Optional[str] = None
    players: list[PlayerOut]
    scores: list[ScoreOut]
    created_at: datetime


class LeaderboardEntry(BaseModel):
    email: str
    display_name: str
    matches_played: int
    wins: int
    win_rate: float
