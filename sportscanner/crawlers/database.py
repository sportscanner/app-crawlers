import json
import os
import uuid
from datetime import date, datetime, time, timedelta
from enum import Enum
from functools import cache
from typing import List

import sqlmodel
from dotenv import load_dotenv
from loguru import logger as logging
from pydantic import UUID4, ValidationError
from sqlalchemy import Engine, text
from sqlmodel import Field, Session, SQLModel, create_engine, delete, select

from sportscanner.crawlers import config
from sportscanner.crawlers.config import SportsCentre

# Check for an environment variable to determine the environment
env_file = ".env" if os.getenv("ENV") == "production" else "dev.env"
# Load the appropriate .env file
load_dotenv(dotenv_path=env_file)

database_name: str = "sportscanner"
connection_string = os.getenv(
    "DB_CONNECTION_STRING"
)
engine_configs = {"timeout": 5}
engine = create_engine(connection_string, pool_pre_ping=True, echo=False)


class PipelineRefreshStatus(Enum):
    RUNNING = "Running"
    COMPLETED = "Completed"
    OBSOLETE = "Obsolete"


class SportScanner(SQLModel, table=True):
    """Table contains records of slots fetched from sport centres
    Original Model: UnifiedParserSchema -> Mapped to: SportScanner
    """

    uuid: str = Field(primary_key=True)
    category: str
    starting_time: time
    ending_time: time
    date: date
    price: str
    spaces: int
    organisation: str
    last_refreshed: datetime
    booking_url: str | None

    venue_slug: str = Field(default=None, foreign_key="sportsvenue.slug")


class SportsVenue(SQLModel, table=True):
    """Table containing information on Sports centres
    Original Model: SportsCentre -> Mapped to: SportsVenue
    """

    venue_name: str
    slug: str = Field(primary_key=True)
    organisation_name: str | None
    organisation_hash: str | None
    parser_uuid: UUID4
    postcode: str
    latitude: float
    longitude: float


class RefreshMetadata(SQLModel, table=True):
    """Table containing Refresh data, and if refresh is in progress"""

    id: int = Field(default=None, primary_key=True)
    last_refreshed: datetime
    refresh_status: str


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


def create_db_and_tables(engine):
    """Creates non-existing tables in db using Class arguments `table=True` which
    registers SQLModel inheritted class into a Table schema
    """
    SQLModel.metadata.create_all(engine)


def load_sports_centre_mappings(engine):
    """Loads sports centre lookup sheet to Table: SportsVenue"""
    with open(f"./{config.MAPPINGS}", "r") as file:
        raw_sports_centres = json.load(file)
        try:
            sports_centre_lists: List[SportsCentre] = [
                SportsCentre(**item) for item in raw_sports_centres
            ]
            logging.success("JSON data is valid according to the Pydantic model!")
        except ValidationError as error:
            logging.error(
                f"JSON data is not valid according to the Pydantic model:\n {error}"
            )
            raise RuntimeError

    logging.debug("Loading sports venue mappings data to database")
    with Session(engine) as session:
        for sports_centre in sports_centre_lists:
            session.add(
                SportsVenue(
                    venue_name=sports_centre.venue_name,
                    slug=sports_centre.slug,
                    organisation_name=sports_centre.organisation_name,
                    organisation_hash=sports_centre.organisation_hash,
                    parser_uuid=sports_centre.parser_uuid,
                    postcode=sports_centre.location.postcode,
                    latitude=sports_centre.location.latitude,
                    longitude=sports_centre.location.longitude,
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
        statement = delete(SportScanner).where(
            SportScanner.organisation == organisation
        )
        results = session.exec(statement)
        logging.debug(
            f"Loading fresh {len(slots_from_all_venues)} records to organisation: {organisation}"
        )
        for slots in slots_from_all_venues:
            orm_object = SportScanner(
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


def delete_all_items_and_insert_fresh_to_db(slots_from_all_venues):
    """Inserts the slots for an Organisation one by one into the table: SportScanner"""
    with Session(engine) as session:
        statement = delete(SportScanner)
        results = session.exec(statement)
        logging.debug(
            f"Loading fresh data items to db: {len(slots_from_all_venues)}"
        )
        for slots in slots_from_all_venues:
            orm_object = SportScanner(
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


def get_all_rows(engine, table: sqlmodel.main.SQLModelMetaclass, expression: select):
    """Returns all rows from full table or selected columns
    Select columns via: select(table.columnA, table.columnB)
    """
    with Session(engine) as session:
        rows = session.exec(expression).all()
    return rows


# TODO: need to work on logic so consecutive sorting is done by SQL views
def create_temporary_view_consecutive_ordering(engine):
    # Define the raw SQL query to check if the view exists
    check_view_query = """
    SELECT count(name)
    FROM sqlite_master
    WHERE type='view' AND name='consecutive_slots_view';
    """

    # Execute the raw SQL query to check if the view exists
    with engine.connect() as connection:
        result = connection.execute(text(check_view_query))
        view_exists = result.scalar()

    # If the view doesn't exist, create it
    if not view_exists:
        create_view_query = """
        CREATE VIEW consecutive_slots_view AS
        SELECT
            uuid,
            venue_slug,
            category,
            starting_time,
            ending_time,
            date,
            price,
            spaces,
            organisation,
            last_refreshed
        FROM
            sportscanner AS s1
        WHERE 
            spaces > 0
            AND EXISTS (
                SELECT 1
                FROM sportscanner AS s2
                WHERE s1.venue_slug = s2.venue_slug
                  AND s1.date = s2.date
                  AND s1.starting_time <= s2.ending_time
                  AND s1.ending_time >= s2.starting_time
                  AND s1.uuid != s2.uuid
            )
        ORDER BY
            venue_slug,
            date,
            starting_time;
        """

        # Execute the raw SQL query to create the view
        with engine.connect() as connection:
            connection.execute(text(create_view_query))


@cache
def initialize_db_and_tables(engine):
    logging.info(f"Creating database: `{database_name}`")
    create_db_and_tables(engine)
    update_refresh_status_for_pipeline(
        engine, refresh_status=PipelineRefreshStatus.OBSOLETE
    )
    truncate_table(engine, table=SportScanner)
    truncate_table(engine, table=SportsVenue)
    load_sports_centre_mappings(engine)


def get_all_sports_venues(engine) -> List[SportsVenue]:
    sports_venues: List[db.SportsVenue] = get_all_rows(
        engine, SportsVenue,
        select(SportsVenue)
    )
    return sports_venues


if __name__ == "__main__":
    logging.info("Database being initialised, cache deleted and mappings reloaded")
    initialize_db_and_tables(engine)
