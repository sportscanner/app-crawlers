from datetime import date, datetime, time, timedelta
from datetime import date as Date
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
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
    # Total bookable capacity of the session, when the provider exposes it
    # (e.g. CourtReserve's MaxMembersOnEvent). Nullable: whole-court providers
    # and rows written before this column existed have no capacity.
    capacity: Optional[int] = None

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
    # Total bookable capacity of the session, when the provider exposes it
    # (e.g. CourtReserve's MaxMembersOnEvent). Nullable: whole-court providers
    # and rows written before this column existed have no capacity.
    capacity: Optional[int] = None

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
    # Total bookable capacity of the session, when the provider exposes it
    # (e.g. CourtReserve's MaxMembersOnEvent). Nullable: whole-court providers
    # and rows written before this column existed have no capacity.
    capacity: Optional[int] = None

    # True/False when the provider exposes indoor-vs-outdoor court metadata;
    # None means unknown/unverified.
    indoor: Optional[bool] = None

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
    # Total bookable capacity of the session, when the provider exposes it
    # (e.g. CourtReserve's MaxMembersOnEvent). Nullable: whole-court providers
    # and rows written before this column existed have no capacity.
    capacity: Optional[int] = None

    # True/False when the provider exposes indoor-vs-outdoor court metadata;
    # None means unknown/unverified.
    indoor: Optional[bool] = None

    composite_key: str = Field(default=None, foreign_key="public.sportsvenue.composite_key")
    __tablename__ = "padel"
    __table_args__ = {"schema": "public"}


class TennisMasterTable(SQLModel, table=True):
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
    # Total bookable capacity of the session, when the provider exposes it
    # (e.g. CourtReserve's MaxMembersOnEvent). Nullable: whole-court providers
    # and rows written before this column existed have no capacity.
    capacity: Optional[int] = None

    # True/False when the provider exposes indoor-vs-outdoor court metadata;
    # None means unknown/unverified.
    indoor: Optional[bool] = None

    composite_key: str = Field(default=None, foreign_key="public.sportsvenue.composite_key")
    __tablename__ = "tennis"
    __table_args__ = {"schema": "public"}


class SlotHistory(SQLModel, table=True):
    """One row per slot across all sports, kept after the slot has passed.

    The master tables only hold today-forward slots, and once a slot starts its
    provider stops listing it, so the stale-marking UPDATE flips it to spaces=0.
    This table freezes each slot's last observation *before* it started, which is
    what the market insights (occupancy, booking value, price history) read from.
    Keyed on the natural slot identity rather than `uid`, because Tower Hamlets'
    truncate-and-reload path assigns a fresh random uid on every run.
    """

    sport: str = Field(primary_key=True)
    composite_key: str = Field(primary_key=True)
    date: Date = Field(primary_key=True)
    starting_time: time = Field(primary_key=True)
    ending_time: time = Field(primary_key=True)
    starts_at: datetime = Field(index=True)
    duration_min: int
    price: str
    # Parsed from `price`; NULL when the provider listed no usable price.
    price_gbp: Optional[float] = None
    first_spaces: int
    last_spaces: int
    max_spaces: int
    capacity: Optional[int] = None
    indoor: Optional[bool] = None
    # Europe/London wall-clock time of the first/last pipeline run that saw the
    # slot, so it compares directly with `starts_at`.
    first_seen: datetime
    last_seen: datetime
    observations: int = 1

    __tablename__ = "slot_history"
    __table_args__ = {"schema": "public"}


class DailyPriceSnapshot(SQLModel, table=True):
    """Last genuine quote for a schedule sample on each London observation day.

    Previous days are immutable. Session duration is part of the identity so a
    40-minute leisure-centre tariff is never compared to a 60-minute tariff.
    """

    sport: str = Field(primary_key=True)
    composite_key: str = Field(primary_key=True)
    observed_on: Date = Field(primary_key=True)
    dow: int = Field(primary_key=True)
    starting_time: time = Field(primary_key=True)
    duration_min: int = Field(primary_key=True)
    price_per_hour: float
    observed_at: datetime
    days_ahead: int

    __tablename__ = "daily_price_snapshot"
    __table_args__ = {"schema": "public"}


class DailySupplySnapshot(SQLModel, table=True):
    """Observed public supply, not a record of venue opening dates."""

    sport: str = Field(primary_key=True)
    composite_key: str = Field(primary_key=True)
    observed_on: Date = Field(primary_key=True)
    courts: int
    observed_at: datetime

    __tablename__ = "daily_supply_snapshot"
    __table_args__ = {"schema": "public"}


class CrawlJob(SQLModel, table=True):
    """Durable per-(provider, venue, date) crawl queue row.

    One row per unique venue/date/provider. The scheduler re-arms a completed
    row for the next freshness tier instead of inserting a new one; workers
    claim due rows with FOR UPDATE SKIP LOCKED. See docs/crawler-scheduling.md.
    """

    __tablename__ = "crawl_job"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "composite_key",
            "slot_date",
            name="uq_crawl_job_provider_venue_date",
        ),
        Index(
            "ix_crawl_job_due",
            "provider",
            "run_after",
            postgresql_where=text("claimed_at IS NULL"),
        ),
        {"schema": "public"},
    )

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    provider: str
    sport: str
    composite_key: str
    slot_date: Date
    tier: int = Field(sa_column=Column(SmallInteger, nullable=False))
    run_after: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    claimed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    claimed_by: Optional[str] = None
    attempts: int = Field(
        default=0,
        sa_column=Column(
            SmallInteger, nullable=False, server_default=text("0"), default=0
        ),
    )
    last_error: Optional[str] = None
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class CrawlSourceStatus(SQLModel, table=True):
    """Last successful/attempted observation for a provider venue/date.

    Freshness is measured from `last_success_at`, never from `last_attempt_at`.
    The scheduler reads this table to compute each job's next `run_after`.
    """

    __tablename__ = "crawl_source_status"
    __table_args__ = (
        Index(
            "ix_crawl_source_status_provider_date",
            "provider",
            "slot_date",
        ),
        {"schema": "public"},
    )

    provider: str = Field(primary_key=True)
    composite_key: str = Field(primary_key=True)
    slot_date: Date = Field(primary_key=True)
    sport: str
    last_success_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_attempt_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_error: Optional[str] = None
    slots_found: Optional[int] = None


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


class McpAuthorizedClient(SQLModel, table=True):
    """
    Tracks which OAuth clients (Claude, Cursor, etc.) a user has authorized
    for the MCP server via the Kinde OAuth proxy flow (see `sportscanner/mcp/`).

    `access_jti`/`refresh_jti` are the FastMCP-issued token IDs for this grant
    (`jti` claim) - revoking deletes their entries from the OAuth proxy's own
    `_jti_mapping_store`, which every authenticated MCP request and refresh
    checks against, so revocation takes effect immediately.
    """

    __tablename__ = "mcp_authorized_clients"
    __table_args__ = {"schema": "public"}

    id: str = Field(primary_key=True)
    kinde_user_id: str = Field(
        foreign_key="public.users.kinde_user_id",
        index=True,
    )
    client_id: str
    client_name: str
    access_jti: str
    refresh_jti: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    revoked: bool = Field(default=False)
