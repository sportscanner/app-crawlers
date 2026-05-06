import enum
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Column, String
from sqlalchemy import JSON, Numeric
import sqlalchemy
from sqlmodel import Field, Session, SQLModel, create_engine, delete, select, Column, String
from sqlalchemy.dialects.postgresql import ARRAY

class SportsVenue(SQLModel, table=True):
    """Table containing information on Sports centres
    Root Raw Data Model: SportsVenueMappingModel -> flattened to postgres Table: sportsvenue
    """
    composite_key: str = Field(primary_key=True)
    organisation: str
    organisation_website: str
    venue_name: str
    slug: str
    postcode: Optional[str]
    address: Optional[str]
    latitude: float
    longitude: float
    sports: List[str] = Field(sa_column=Column(ARRAY(String)))

    __table_args__ = {"schema": "public"}


class BadmintonMasterTable(SQLModel, table=True):
    """Table contains records of slots fetched from sport centres
    Original Model: UnifiedParserSchema -> Mapped to: SportScanner
    """
    uid: str = Field(primary_key=True)
    category: str
    starting_time: time
    ending_time: time
    date: date
    price: str
    spaces: int
    last_refreshed: datetime
    booking_url: str | None

    composite_key: str = Field(default=None, foreign_key="public.sportsvenue.composite_key")
    __tablename__ = "badminton"
    __table_args__ = {"schema": "public"}


class BadmintonStagingTable(SQLModel, table=True):
    """Table contains records of slots fetched from sport centres
    Original Model: UnifiedParserSchema -> Mapped to: SportScanner
    """
    uid: str = Field(primary_key=True)
    category: str
    starting_time: time
    ending_time: time
    date: date
    price: str
    spaces: int
    last_refreshed: datetime
    booking_url: str | None

    composite_key: str = Field(default=None, foreign_key="public.sportsvenue.composite_key")

    __tablename__ = "badminton"
    __table_args__ = {"schema": "staging"}

class SquashMasterTable(SQLModel, table=True):
    """Table contains records of slots fetched from sport centres
    Original Model: UnifiedParserSchema -> Mapped to: SportScanner
    """
    uid: str = Field(primary_key=True)
    category: str
    starting_time: time
    ending_time: time
    date: date
    price: str
    spaces: int
    last_refreshed: datetime
    booking_url: str | None

    composite_key: str = Field(default=None, foreign_key="public.sportsvenue.composite_key")
    __tablename__ = "squash"
    __table_args__ = {"schema": "public"}


class SquashStagingTable(SQLModel, table=True):
    """Table contains records of slots fetched from sport centres
    Original Model: UnifiedParserSchema -> Mapped to: SportScanner
    """
    uid: str = Field(primary_key=True)
    category: str
    starting_time: time
    ending_time: time
    date: date
    price: str
    spaces: int
    last_refreshed: datetime
    booking_url: str | None
    
    composite_key: str = Field(default=None, foreign_key="public.sportsvenue.composite_key")
    __tablename__ = "squash"
    __table_args__ = {"schema": "staging"}


class PickleballMasterTable(SQLModel, table=True):
    """Table contains records of slots fetched from sport centres
    Original Model: UnifiedParserSchema -> Mapped to: SportScanner
    """
    uid: str = Field(primary_key=True)
    category: str
    starting_time: time
    ending_time: time
    date: date
    price: str
    spaces: int
    last_refreshed: datetime
    booking_url: str | None

    composite_key: str = Field(default=None, foreign_key="public.sportsvenue.composite_key")
    __tablename__ = "pickleball"
    __table_args__ = {"schema": "public"}


class PickleballStagingTable(SQLModel, table=True):
    """Table contains records of slots fetched from sport centres
    Original Model: UnifiedParserSchema -> Mapped to: SportScanner
    """
    uid: str = Field(primary_key=True)
    category: str
    starting_time: time
    ending_time: time
    date: date
    price: str
    spaces: int
    last_refreshed: datetime
    booking_url: str | None
    
    composite_key: str = Field(default=None, foreign_key="public.sportsvenue.composite_key")
    __tablename__ = "pickleball"
    __table_args__ = {"schema": "staging"}

class RefreshMetadata(SQLModel, table=True):
    """Table containing Refresh data, and if refresh is in progress"""

    id: int = Field(default=None, primary_key=True)
    last_refreshed: datetime
    refresh_status: str


class Notification(SQLModel, table=True):
    """Global notification messages shown to users in the app."""

    __tablename__ = "notification"
    __table_args__ = {"schema": "public"}

    id: Optional[str] = Field(default=None, primary_key=True)
    title: str
    message: str
    active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class NotificationAck(SQLModel, table=True):
    """Per-user acknowledgement (dismissal) of a notification."""

    __tablename__ = "notification_ack"
    __table_args__ = {"schema": "public"}

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str  # Kinde user id
    notification_id: str = Field(foreign_key="public.notification.id")
    acknowledged_at: datetime = Field(default_factory=datetime.utcnow)


class User(SQLModel, table=True):
    """Core user identity — one row per Kinde account."""

    __tablename__ = "users"
    __table_args__ = {"schema": "public"}

    kinde_user_id: str = Field(primary_key=True)
    full_name: Optional[str] = None
    email: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UserPreferences(SQLModel, table=True):
    """
    Flexible user preferences stored as JSONB.
    Adding new preference fields never requires a schema migration —
    just write the new key into the JSON blob.

    Preference keys (all optional, evolve over time):
      postcode, searchRadius, usePostcodeSearch, preferredVenues,
      goals, skills, availability, customPostcodes, ...
    """

    __tablename__ = "user_preferences"
    __table_args__ = {"schema": "public"}

    kinde_user_id: str = Field(
        primary_key=True,
        foreign_key="public.users.kinde_user_id",
    )
    preferences: dict = Field(default={}, sa_column=Column(JSON, nullable=False))
    onboarding_completed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MatchType(str, enum.Enum):
    SINGLES = "SINGLES"
    DOUBLES = "DOUBLES"


class MatchStatus(str, enum.Enum):
    LOGGED = "LOGGED"
    SPLIT = "SPLIT"


class Match(SQLModel, table=True):
    """A logged match session — created after playing, with scores and participants."""

    __tablename__ = "match"
    __table_args__ = {"schema": "public"}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_by: str = Field(foreign_key="public.users.kinde_user_id")
    venue_name: str
    sport: str
    match_type: MatchType
    played_at: datetime
    duration_minutes: Optional[int] = None
    winning_team: Optional[int] = None  # 1 or 2; null if not determined
    total_cost: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(10, 2), nullable=True))
    status: MatchStatus = Field(default=MatchStatus.LOGGED)
    splitwise_expense_id: Optional[str] = None
    splitwise_error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MatchPlayer(SQLModel, table=True):
    """A player in a Match — identified by email, assigned to a team."""

    __tablename__ = "match_player"
    __table_args__ = {"schema": "public"}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    match_id: uuid.UUID = Field(foreign_key="public.match.id")
    email: str
    display_name: str
    team: int  # 1 or 2
    is_creator: bool = Field(default=False)
    splitwise_notified: Optional[bool] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MatchScore(SQLModel, table=True):
    """Score for one game (set) within a Match."""

    __tablename__ = "match_score"
    __table_args__ = {"schema": "public"}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    match_id: uuid.UUID = Field(foreign_key="public.match.id")
    game_number: int  # 1, 2, 3...
    team1_score: int
    team2_score: int
