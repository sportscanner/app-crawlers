import json
from pydantic import BaseModel, UUID4, ValidationError
import sqlmodel
from sqlmodel import Field, Session, SQLModel, create_engine, delete, select, and_
from datetime import time, datetime, date
from shuttlebot import config
from shuttlebot.config import SportsCentre
from loguru import logger as logging
import uuid
from sqlalchemy import text
from functools import cache

sqlite_file_name = "sportscanner.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, echo=False)


class SportScanner(SQLModel, table=True):
    """Table contains records of slots fetched from sport centres
    Original Model: UnifiedParserSchema -> Mapped to: SportScanner
    """
    uuid: str = Field(primary_key=True)
    venue_slug: str
    category: str
    starting_time: time
    ending_time: time
    date: date
    price: str
    spaces: int
    organisation: str
    last_refreshed: datetime


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
            sports_centre_lists: List[SportsCentre] = [SportsCentre(**item) for item in
                                                       raw_sports_centres]
            logging.success("JSON data is valid according to the Pydantic model!")
        except ValidationError as error:
            logging.error(f"JSON data is not valid according to the Pydantic model:\n {error}")
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
                    longitude=sports_centre.location.longitude
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
        logging.warning(f"Table: {table} has been truncated. Deleted rows: {result.rowcount}")


def delete_and_insert_slots_to_database(slots_from_all_venues, organisation: str):
    """Inserts the slots for an Organisation one by one into the table: SportScanner"""
    with Session(engine) as session:
        statement = delete(SportScanner).where(SportScanner.organisation == organisation)
        results = session.exec(statement)
        logging.debug(f"Loading fresh {len(slots_from_all_venues)} records to organisation: {organisation}")
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
                last_refreshed=slots.last_refreshed
            )
            session.add(orm_object)
        session.commit()


def get_all_rows(engine, table: sqlmodel.main.SQLModelMetaclass, expression: select):
    """Returns all rows from full table or selected columns
    Select columns via: select(table.columnA, table.columnB)
    """
    with Session(engine) as session:
        rows = session.exec(
            expression
        ).all()
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
    logging.info(f"Creating database {sqlite_url}")
    create_db_and_tables(engine)
    truncate_table(engine, table=SportsVenue)
    load_sports_centre_mappings(engine)
    
    
if __name__ == "__main__":
    initialize_db_and_tables(engine)
