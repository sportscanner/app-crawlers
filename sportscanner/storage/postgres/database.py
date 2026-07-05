import uuid
from enum import Enum

import sqlmodel
from sportscanner.logger import logging
from sqlalchemy import Engine, text, func, update
from sqlalchemy.dialects.postgresql import insert
import hashlib

import sportscanner.storage.postgres.tables
from sportscanner.schemas import SportsVenueMappingModel
from sportscanner.storage.postgres.utils import *
from sportscanner.storage.postgres.tables import *
from sportscanner.utils import get_sports_venue_mappings_from_raw, timeit
from sportscanner.variables import settings

connection_string = settings.DB_CONNECTION_STRING

engine_configs = {"timeout": 5}
# Aiven max_connections is 20 (3 reserved for SUPERUSER). Cap each process
# at 5 total so multiple workers + the crawler pipeline can coexist.
engine = create_engine(
    connection_string,
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=2,
    pool_recycle=300,
    pool_timeout=10,
    echo=False,
)


class PipelineRefreshStatus(Enum):
    RUNNING = "Running"
    COMPLETED = "Completed"
    OBSOLETE = "Obsolete"


def get_refresh_status_for_pipeline(engine: Engine):
    """GET status of current refresh status from RefreshMetadata table"""
    with Session(engine) as session:
        # Get the existing record (should be only one)
        existing_record = session.exec(select(RefreshMetadata)).first()
    return existing_record.refresh_status


def update_refresh_status_for_pipeline(
    engine: Engine, refresh_status: PipelineRefreshStatus
):
    """UPDATE status of current refresh status from RefreshMetadata table"""
    with Session(engine) as session:
        # Get the existing record (should be only one)
        existing_record = session.exec(select(RefreshMetadata)).first()
        if existing_record:
            existing_record.refresh_status = refresh_status.value
            existing_record.last_refreshed = datetime.now()
        session.commit()


def pipeline_refresh_decision_based_on_interval(
    engine: Engine, refresh_interval: timedelta
):
    """Updates the refresh status if it's older than refresh_interval (class: datetime.timedelta)"""
    x_minutes_ago = datetime.now() - refresh_interval
    with Session(engine) as session:
        # Get the existing record (should be only one)
        existing_record = session.exec(select(RefreshMetadata)).first()
        if existing_record:
            if existing_record.last_refreshed < x_minutes_ago:
                logging.info(
                    f"Data is older than `x` minutes ago: {refresh_interval}, refresh needed"
                )
                # Update existing record
                existing_record.refresh_status = PipelineRefreshStatus.OBSOLETE.value
                existing_record.last_refreshed = datetime.now()
            elif existing_record.refresh_status == PipelineRefreshStatus.OBSOLETE.value:
                logging.info(
                    f"Metadata marked as `OBSOLETE` - indicates a system restart"
                )
                existing_record.last_refreshed = datetime.now()
            else:
                logging.info(
                    f"Data is within `x` minutes ago range: {refresh_interval}, NO refresh needed"
                )
        else:
            """
            Create a new record if none exists
            can happen when setup is initialised onto a new database or infra
            """
            new_record = RefreshMetadata(
                refresh_status=PipelineRefreshStatus.OBSOLETE.value,
                last_refreshed=datetime.now(),
            )
            session.add(new_record)
        session.commit()


def load_sports_centre_mappings(engine):
    """Loads sports centre lookup sheet to Table: SportsVenue"""
    sports_centre_lists: SportsVenueMappingModel = get_sports_venue_mappings_from_raw()
    logging.debug("Loading sports venue mappings data to database")
    with Session(engine) as session:
        for organisation in sports_centre_lists.root:
            for venue in organisation.venues:
                session.add(
                    SportsVenue(
                        composite_key=generate_composite_key(
                            [organisation.organisation_website, venue.slug]
                        ),
                        organisation=organisation.organisation,
                        organisation_website=organisation.organisation_website,
                        venue_name=venue.venue_name,
                        slug=venue.slug,
                        postcode=venue.location.postcode,
                        address=venue.location.address,
                        latitude=venue.location.latitude,
                        longitude=venue.location.longitude,
                        sports=venue.sports
                    )
                )
        session.flush()  # write inserts to DB before the UPDATE can see them
        # Ensure srid column is populated for distance calculations
        session.execute(text("UPDATE sportsvenue SET srid = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326) WHERE srid IS NULL"))
        session.commit()
        logging.success("Sports venue mapping successfully loaded to database")


def truncate_table(engine, table: sqlmodel.main.SQLModelMetaclass):
    """Truncates (deletes all rows) in a given Table name/SQL Model class name"""
    with Session(engine) as session:
        statement = delete(table)
        result = session.exec(statement)
        session.commit()
        logging.warning(
            f"Table: {table} has been truncated. Deleted rows: {result.rowcount}"
        )


@timeit
def truncate_and_reload_all(slots_from_all_venues, TableForLoading: sqlmodel.main.SQLModelMetaclass):
    """Inserts the slots for an Organisation one by one into the table: SportScanner"""
    with Session(engine) as session:
        statement = delete(TableForLoading)
        results = session.exec(statement)
        logging.debug(f"Loading fresh data items to db: {len(slots_from_all_venues)}")
        for slots in slots_from_all_venues:
            orm_object = TableForLoading(
                uid=str(uuid.uuid4()),
                composite_key=slots.composite_key,
                category=slots.category,
                starting_time=slots.starting_time,
                ending_time=slots.ending_time,
                date=slots.date,
                price=slots.price,
                spaces=slots.spaces,
                last_refreshed=slots.last_refreshed,
                booking_url=slots.booking_url,
            )
            session.add(orm_object)
        session.commit()



@timeit
def insert_records_to_table(slots_from_all_venues, TableForLoading: sqlmodel.main.SQLModelMetaclass):
    """Bulk upsert slots into a table.

    Also handles stale slots: for any existing slots in DB that are NOT in the incoming
    data (i.e., the API no longer returns them), they will be marked as spaces=0.
    This ensures stale slots don't show old availability.

    Previously this read every existing row for the incoming composite_keys/dates into
    Python, diffed it against the incoming batch, and re-upserted the stale ones — an
    app-side read-modify-write on every pipeline run. Marking stale slots is now a
    single indexed UPDATE (WHERE composite_key/date match AND uid wasn't refreshed),
    so nothing is read back from the DB at all.
    """
    if not slots_from_all_venues:
        logging.warning("No slots provided for insert; skipping.")
        return

    now = datetime.now()

    # De-dup the incoming batch by uid, preferring the entry with spaces > 0. This
    # handles cases where both 40min and 60min API calls return the same slot, but one
    # returns spaces=0 (fallback from an empty response) and one returns real availability.
    uid_to_slots = {}
    for slots in slots_from_all_venues:
        key = f"{slots.composite_key}-{slots.category}-{slots.date}-{slots.starting_time}-{slots.ending_time}"
        uid = hashlib.md5(key.encode("utf-8")).hexdigest()
        existing = uid_to_slots.get(uid)
        if existing is None or (slots.spaces > 0 and existing.spaces == 0):
            uid_to_slots[uid] = slots

    all_data = []
    for uid, slots in uid_to_slots.items():
        all_data.append(dict(
            uid=uid,
            composite_key=slots.composite_key,
            category=slots.category,
            starting_time=slots.starting_time,
            ending_time=slots.ending_time,
            date=slots.date,
            price=slots.price,
            spaces=slots.spaces,
            last_refreshed=slots.last_refreshed,
            booking_url=slots.booking_url,
            starts_at=datetime.combine(slots.date, slots.starting_time),
        ))

    if not all_data:
        logging.warning("No data to insert after processing.")
        return

    composite_keys = {slots.composite_key for slots in slots_from_all_venues}
    dates = {slots.date for slots in slots_from_all_venues}
    incoming_uids = list(uid_to_slots.keys())

    with Session(engine) as session:
        stmt = insert(TableForLoading).values(all_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=['uid'],
            set_={c: stmt.excluded[c] for c in all_data[0] if c != 'uid'}
        )
        session.exec(stmt)

        # Any row already in the DB for these composite_keys/dates that wasn't just
        # refreshed above no longer appears in the source API response — mark it
        # unavailable rather than leaving stale availability showing.
        mark_stale_stmt = (
            update(TableForLoading)
            .where(TableForLoading.composite_key.in_(composite_keys))
            .where(TableForLoading.date.in_(dates))
            .where(TableForLoading.spaces != 0)
            .where(TableForLoading.uid.not_in(incoming_uids))
            .values(spaces=0, last_refreshed=now)
        )
        stale_result = session.exec(mark_stale_stmt)

        session.commit()
        logging.success(
            f"Upserted {len(all_data)} slots into {TableForLoading.__tablename__} "
            f"(marked {stale_result.rowcount} stale rows unavailable)"
        )


def get_all_rows(engine, table: sqlmodel.main.SQLModelMetaclass, expression: select, params=None):
    """Returns all rows from full table or selected columns
    Select columns via: select(table.columnA, table.columnB)
    """
    with Session(engine) as session:
        if params:
            rows = session.exec(expression, **params).all()
        else:
            rows = session.exec(expression).all()
    return rows


def create_db_and_tables(engine):
    """Creates required schemas (if not exist) and then tables."""
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS public"))
        conn.commit()

    SQLModel.metadata.create_all(
        bind=engine,
        tables=[
            SportsVenue.__table__,
            BadmintonMasterTable.__table__,
            SquashMasterTable.__table__,
            PickleballMasterTable.__table__,
            PadelMasterTable.__table__,
            User.__table__,
            UserPreferences.__table__,
            ApiToken.__table__,
            Notification.__table__,
            NotificationAck.__table__,
        ]
    )

    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text(
            "ALTER TABLE public.sportsvenue ADD COLUMN IF NOT EXISTS srid geometry(Point, 4326)"
        ))
        conn.commit()

    ensure_starts_at_column(engine)
    ensure_performance_indexes(engine)


_SLOT_TABLES = ("badminton", "squash", "pickleball", "padel")


def ensure_starts_at_column(engine):
    """Additive-only migration — adds `starts_at` and backfills it from existing
    date+starting_time. Safe to run repeatedly against a live DB (each statement is
    idempotent: ADD COLUMN IF NOT EXISTS, and the backfill only touches NULL rows)."""
    with engine.connect() as conn:
        for table in _SLOT_TABLES:
            conn.execute(text(f'ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS starts_at timestamp'))
            conn.execute(text(f'''
                UPDATE public.{table}
                SET starts_at = (date::text || ' ' || starting_time::text)::timestamp
                WHERE starts_at IS NULL
            '''))
        conn.commit()


def ensure_performance_indexes(engine):
    """Additive-only index migration — safe to run repeatedly against a live DB.

    Every search filters `composite_key IN (...) AND date == X AND spaces > 0`, and
    delete_past_slots() filters `date < today()`; with only the primary key (uid) to
    go on, both were full table scans. Adds:
      - a plain composite index (composite_key, date) per slot table — covers the
        general composite_key/date lookups (search, delete_past_slots, the
        insert-time stale-marking UPDATE).
      - a partial composite index on the same columns WHERE spaces > 0 — near-free
        given spaces > 0 is search's dominant filter; keeps the index small since
        stale/unavailable rows (spaces = 0) are excluded from it entirely.
      - a GiST index on sportsvenue.srid — ST_DWithin/ST_Distance in /venues/near
        would otherwise sequential-scan as venue count grows.
    """
    with engine.connect() as conn:
        for table in _SLOT_TABLES:
            conn.execute(text(
                f'CREATE INDEX IF NOT EXISTS ix_{table}_composite_key_date '
                f'ON public.{table} (composite_key, date)'
            ))
            conn.execute(text(
                f'CREATE INDEX IF NOT EXISTS ix_{table}_composite_key_date_active '
                f'ON public.{table} (composite_key, date) WHERE spaces > 0'
            ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_sportsvenue_srid_gist "
            "ON public.sportsvenue USING GIST (srid)"
        ))
        conn.commit()


def initialize_db_and_tables(engine):
    create_db_and_tables(engine)
    truncate_table(engine, table=BadmintonMasterTable)
    truncate_table(engine, table=SquashMasterTable)
    truncate_table(engine, table=PickleballMasterTable)
    truncate_table(engine, table=PadelMasterTable)
    truncate_table(engine, table=SportsVenue)
    load_sports_centre_mappings(engine)


def get_all_sports_venues(engine) -> List[SportsVenue]:
    sports_venues: List[sportscanner.storage.postgres.tables.SportsVenue] = get_all_rows(
        engine, SportsVenue, select(SportsVenue)
    )
    return sports_venues


@timeit
def truncate_by_composite_key_and_reload(slots_from_all_venues, TableForLoading: sqlmodel.main.SQLModelMetaclass):
    """
    Deletes rows for matching composite_key values in TableForLoading 
    and inserts fresh slots for those keys.
    """
    if not slots_from_all_venues:
        logging.warning("No slots provided for `Truncate by Composite Key and Reload`; skipping.")
        return

    # Collect unique composite keys from incoming data
    composite_keys_to_delete = {slots.composite_key for slots in slots_from_all_venues}

    with Session(engine) as session:
        # Delete only matching composite_key rows
        delete_stmt = delete(TableForLoading).where(
            TableForLoading.composite_key.in_(composite_keys_to_delete)
        )
        deleted_count = session.exec(delete_stmt)
        logging.info(f"Deleted {deleted_count.rowcount} rows from {TableForLoading.__tablename__} for composite_keys={composite_keys_to_delete}")

        # Insert new rows
        for slots in slots_from_all_venues:
            orm_object = TableForLoading(
                uid=str(uuid.uuid4()),
                composite_key=slots.composite_key,
                category=slots.category,
                starting_time=slots.starting_time,
                ending_time=slots.ending_time,
                date=slots.date,
                price=slots.price,
                spaces=slots.spaces,
                last_refreshed=slots.last_refreshed,
                booking_url=slots.booking_url,
                starts_at=datetime.combine(slots.date, slots.starting_time),
            )
            session.add(orm_object)

        session.commit()
        logging.success(f"Reloaded {len(slots_from_all_venues)} slots into {TableForLoading.__tablename__}")


def delete_past_slots(TableForLoading: sqlmodel.main.SQLModelMetaclass) -> int:
    """Housekeeping: delete slots whose date has already passed.

    The crawl window only ever moves forward and search/display surface only
    future slots (starting_time > NOW()), so past-date rows are pure dead weight.
    Without this, each day the date that ages out of the crawl window is never
    touched again and lingers forever, so the table grows unbounded. Padel — the
    highest-volume sport — hit the DB size limit within ~2 weeks (over half its
    rows were past-date orphans). Runs every pipeline for every sport.
    """
    with Session(engine) as session:
        result = session.exec(
            delete(TableForLoading).where(TableForLoading.date < date.today())
        )
        session.commit()
        logging.info(
            f"Housekeeping: deleted {result.rowcount} past-date rows from {TableForLoading.__tablename__}"
        )
        return result.rowcount


if __name__ == "__main__":
    logging.info("Database being initialised, cache deleted and mappings reloaded")
    initialize_db_and_tables(engine)
