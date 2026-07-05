from datetime import date, datetime, time, timedelta
from typing import List, Optional

from sqlalchemy import Column, String
import sqlalchemy
from sqlmodel import Field, Session, SQLModel, create_engine, delete, select, Column, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

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
    # Precomputed date+starting_time, populated at write time (see insert_records_to_table).
    # Lets "is this slot still bookable" be a plain indexed timestamp comparison instead of
    # a per-row to_timestamp(concat(date, starting_time)) computed at query time, which
    # can't use an index. Nullable for rows written before this column existed.
    starts_at: Optional[datetime] = None

    composite_key: str = Field(default=None, foreign_key="public.sportsvenue.composite_key")
    __tablename__ = "badminton"
    __table_args__ = {"schema": "public"}


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
    # Precomputed date+starting_time, populated at write time (see insert_records_to_table).
    # Lets "is this slot still bookable" be a plain indexed timestamp comparison instead of
    # a per-row to_timestamp(concat(date, starting_time)) computed at query time, which
    # can't use an index. Nullable for rows written before this column existed.
    starts_at: Optional[datetime] = None

    composite_key: str = Field(default=None, foreign_key="public.sportsvenue.composite_key")
    __tablename__ = "squash"
    __table_args__ = {"schema": "public"}


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
    # Precomputed date+starting_time, populated at write time (see insert_records_to_table).
    # Lets "is this slot still bookable" be a plain indexed timestamp comparison instead of
    # a per-row to_timestamp(concat(date, starting_time)) computed at query time, which
    # can't use an index. Nullable for rows written before this column existed.
    starts_at: Optional[datetime] = None

    composite_key: str = Field(default=None, foreign_key="public.sportsvenue.composite_key")
    __tablename__ = "pickleball"
    __table_args__ = {"schema": "public"}


class PadelMasterTable(SQLModel, table=True):
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
    # Precomputed date+starting_time, populated at write time (see insert_records_to_table).
    # Lets "is this slot still bookable" be a plain indexed timestamp comparison instead of
    # a per-row to_timestamp(concat(date, starting_time)) computed at query time, which
    # can't use an index. Nullable for rows written before this column existed.
    starts_at: Optional[datetime] = None

    composite_key: str = Field(default=None, foreign_key="public.sportsvenue.composite_key")
    __tablename__ = "padel"
    __table_args__ = {"schema": "public"}


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
    preferences: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    onboarding_completed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ApiToken(SQLModel, table=True):
    """
    Personal API tokens for programmatic + MCP access, tied to a user account.

    The raw token is shown to the user exactly once at creation time; only a
    SHA-256 hash is persisted, so a leaked database never exposes usable
    credentials. `token_prefix` stores a short, non-secret identifier
    (e.g. "ssc_A1b2C3d") purely so the UI can show which token is which.
    """

    __tablename__ = "api_tokens"
    __table_args__ = {"schema": "public"}

    id: str = Field(primary_key=True)
    kinde_user_id: str = Field(
        foreign_key="public.users.kinde_user_id",
        index=True,
    )
    name: str
    token_prefix: str
    token_hash: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = Field(default=None)
    last_used_at: Optional[datetime] = Field(default=None)
    revoked: bool = Field(default=False)
