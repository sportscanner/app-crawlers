import uuid
from datetime import date, datetime, time, timedelta
from typing import List, Optional
from uuid import uuid4

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


class BusinessPartner(SQLModel, table=True):
    """Business accounts for Sportscanner Business portal."""

    __tablename__ = "business_partner"
    __table_args__ = {"schema": "public"}

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str
    website: str
    kinde_user_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String, nullable=True, unique=True, index=True),
    )
    email: str = Field(sa_column=Column(String, nullable=False, unique=True, index=True))
    password_hash: str
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BusinessApiKey(SQLModel, table=True):
    """API keys used by third-party business integrations."""

    __tablename__ = "business_api_key"
    __table_args__ = {"schema": "public"}

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    partner_id: str = Field(foreign_key="public.business_partner.id", index=True)
    label: str
    key_prefix: str
    key_hash: str = Field(sa_column=Column(String, nullable=False, unique=True, index=True))
    active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_used_at: Optional[datetime] = None


class BusinessVenueAccess(SQLModel, table=True):
    """Many-to-many style mapping of business partner to managed venues."""

    __tablename__ = "business_venue_access"
    __table_args__ = {"schema": "public"}

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    partner_id: str = Field(foreign_key="public.business_partner.id", index=True)
    composite_key: str = Field(foreign_key="public.sportsvenue.composite_key", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BusinessIngestionEvent(SQLModel, table=True):
    """Audit trail for each availability ingest request from portal/integrations."""

    __tablename__ = "business_ingestion_event"
    __table_args__ = {"schema": "public"}

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    partner_id: str = Field(foreign_key="public.business_partner.id", index=True)
    source: str = "portal"
    sport: str
    composite_key: str
    slots_received: int
    slots_written: int
    request_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class ChatSession(SQLModel, table=True):
    """Persisted user chat sessions for the Sportscanner agent."""

    __tablename__ = "chat_session"
    __table_args__ = {"schema": "public"}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    kinde_user_id: str = Field(index=True)
    title: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChatMessage(SQLModel, table=True):
    """Persisted chat messages linked to a chat session."""

    __tablename__ = "chat_message"
    __table_args__ = {"schema": "public"}

    id: Optional[int] = Field(default=None, primary_key=True)
    chat_session_id: str = Field(foreign_key="public.chat_session.id", index=True)
    role: str
    content: str
    used_tools: List[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(String), nullable=False),
    )
    model: Optional[str] = None
    ui_blocks: Optional[dict | list] = Field(default=None, sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=datetime.utcnow)
