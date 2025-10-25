import uuid
from enum import Enum

import sqlmodel
from sportscanner.logger import logging
from sqlalchemy import Engine, text

import sportscanner.storage.postgres.tables
from sportscanner.schemas import SportsVenueMappingModel
from sportscanner.storage.postgres.utils import *
from sportscanner.storage.postgres.tables import *
from sportscanner.utils import get_sports_venue_mappings_from_raw, timeit
from sportscanner.variables import settings

database_name = settings.SQL_DATABASE_NAME
connection_string = settings.DB_CONNECTION_STRING

engine_configs = {"timeout": 5}
engine = create_engine(connection_string, pool_pre_ping=True, echo=False)


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


def delete_and_insert_slots_to_database(slots_from_all_venues, organisation: str):
    """Inserts the slots for an Organisation one by one into the table: SportScanner"""
    with Session(engine) as session:
        statement = delete(BadmintonMasterTable).where(
            BadmintonMasterTable.organisation == organisation
        )
        results = session.exec(statement)
        logging.debug(
            f"Loading fresh {len(slots_from_all_venues)} records to organisation: {organisation}"
        )
        for slots in slots_from_all_venues:
            orm_object = BadmintonMasterTable(
                uuid=str(uuid.uuid4()),
                venue_slug=slots.venue_slug,
                category=slots.category,
                starting_time=slots.starting_time,
                ending_time=slots.ending_time,
                date=slots.date,
                price=slots.price,
                spaces=slots.spaces,
                organisation=slots.organisation,
                last_refreshed=slots.last_refreshed,
                booking_url=slots.booking_url,
            )
            session.add(orm_object)
        session.commit()


@timeit
def delete_all_items_and_insert_fresh_to_db(slots_from_all_venues):
    """Inserts the slots for an Organisation one by one into the table: SportScanner"""
    with Session(engine) as session:
        statement = delete(BadmintonMasterTable)
        results = session.exec(statement)
        logging.debug(f"Loading fresh data items to db: {len(slots_from_all_venues)}")
        for slots in slots_from_all_venues:
            orm_object = BadmintonMasterTable(
                uuid=str(uuid.uuid4()),
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
def truncate_and_reload_all(slots_from_all_venues, TableForLoading: sqlmodel.main.SQLModelMetaclass):
    """Inserts the slots for an Organisation one by one into the table: SportScanner"""
    with Session(engine) as session:
        statement = delete(TableForLoading)
        results = session.exec(statement)
        logging.debug(f"Loading fresh data items to db: {len(slots_from_all_venues)}")
        for slots in slots_from_all_venues:
            orm_object = TableForLoading(
                uuid=str(uuid.uuid4()),
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


def recreate_staging_table():
    with engine.begin() as conn:
        # Drop the table if it exists
        conn.exec_driver_sql("DROP TABLE IF EXISTS badminton_staging;")
        # Recreate using SQLModel metadata
        BadmintonStagingTable.metadata.create_all(bind=conn)

def swap_tables(master: str, staging: str, archive: str):
    """Swap staging table into master position."""
    logging.warning(f"Starting swap between master: `{master}` and staging: `{staging}` - Archive: `{archive}`")
    with engine.connect() as conn:
        with conn.begin():
            logging.warning("Dropping existing Archive tables")
            conn.execute(text(f"DROP TABLE IF EXISTS {archive} CASCADE;"))
            logging.warning("Moving Master table to Archive")
            conn.execute(text(f"ALTER TABLE {master} SET SCHEMA archive;"))
            logging.warning("Moving Staging table to Master")
            # conn.execute(text(f"ALTER TABLE {staging} DROP CONSTRAINT IF EXISTS {master}_pkey;"))
            conn.execute(text(f"ALTER TABLE {staging} SET SCHEMA public;"))
            logging.warning("Housekeeping: Dropping Archive Table")
            conn.execute(text(f"DROP TABLE IF EXISTS {archive} CASCADE;"))


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
    required_schemas = ["public", "staging", "archive"]  # Replace with your actual schemas

    with engine.connect() as conn:
        for schema in required_schemas:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        conn.commit()

    SQLModel.metadata.create_all(
        bind=engine,
        tables=[
            SportsVenue.__table__,
            BadmintonMasterTable.__table__,
            BadmintonStagingTable.__table__,
            SquashMasterTable.__table__,
            SquashStagingTable.__table__,
            PickleballMasterTable.__table__,
            PickleballStagingTable.__table__        
        ]
    )


def initialise_badminton_staging():
    """Creates non-existing tables in db using Class arguments `table=True` which
    registers SQLModel inheritted class into a Table schema
    """
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS staging.badminton;")
    SQLModel.metadata.create_all(
        bind=engine,
        tables=[
            BadmintonStagingTable.__table__,
        ]
    )

def initialise_pickleball_staging():
    """Creates non-existing tables in db using Class arguments `table=True` which
    registers SQLModel inheritted class into a Table schema
    """
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS staging.pickleball;")
    SQLModel.metadata.create_all(
        bind=engine,
        tables=[
            PickleballStagingTable.__table__,
        ]
    )

def initialise_squash_staging():
    """Creates non-existing tables in db using Class arguments `table=True` which
    registers SQLModel inheritted class into a Table schema
    """
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS staging.squash;")
    SQLModel.metadata.create_all(
        bind=engine,
        tables=[
            SquashStagingTable.__table__,
        ]
    )


def initialize_db_and_tables(engine):
    create_db_and_tables(engine)
    truncate_table(engine, table=BadmintonMasterTable)
    truncate_table(engine, table=BadmintonStagingTable)
    truncate_table(engine, table=SquashMasterTable)
    truncate_table(engine, table=SquashStagingTable)
    truncate_table(engine, table=PickleballMasterTable)
    truncate_table(engine, table=PickleballStagingTable)

    truncate_table(engine, table=SportsVenue)
    load_sports_centre_mappings(engine)


def get_all_sports_venues(engine) -> List[SportsVenue]:
    sports_venues: List[sportscanner.storage.postgres.tables.SportsVenue] = get_all_rows(
        engine, SportsVenue, select(SportsVenue)
    )
    return sports_venues


if __name__ == "__main__":
    logging.info("Database being initialised, cache deleted and mappings reloaded")
    initialize_db_and_tables(engine)
