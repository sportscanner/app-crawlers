from datetime import date, datetime, time, timedelta
from typing import List, Optional

from sqlalchemy import Column, String
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
