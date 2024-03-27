import datetime
import json
from pydantic import BaseModel, UUID4, ValidationError
import sqlmodel
from sqlmodel import Field, Session, SQLModel, create_engine, delete, select
from datetime import time, datetime, date
from shuttlebot import config
from shuttlebot.config import SportsCentre
from loguru import logger as logging
import uuid

sqlite_file_name = "sportscanner.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, echo=True)

def create_db_and_tables(engine):
    SQLModel.metadata.create_all(engine)


class SportScanner(SQLModel, table=True):
    """Table contains records of slots fetched from sport centres"""
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
    """Table containing information on Sports centres"""
    venue_name: str
    slug: str = Field(primary_key=True)
    organisation_name: str | None
    organisation_hash: str | None
    parser_uuid: UUID4
    postcode: str
    latitude: float
    longitude: float


def load_sports_centre_mappings(engine):
    """Loads sports centre lookup sheet to db Table"""
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
    with Session(engine) as session:
        statement = delete(table)
        result = session.exec(statement)
        session.commit()
        logging.warning(f"Table: {table} has been truncated. Deleted rows: {result.rowcount}")


def delete_and_insert_slots_to_database(slots_from_all_venues, organisation: str):
    """Inserts the slots one by one into the table: SportScanner"""
    with Session(engine) as session:
        statement = delete(SportScanner).where(SportScanner.organisation == organisation)
        results = session.exec(statement)
        logging.debug(f"Loading fresh {len(slots_from_all_venues)} records to organisation: {organisation}")
        for slots in slots_from_all_venues:
            orm_object = SportScanner(
                uuid=str(uuid.uuid4()),
                name=slots.name,
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
    with Session(engine) as session:
        rows = session.exec(
            expression
        ).all()
    return rows


if __name__ == "__main__":
    # create_db_and_tables(engine)
    # truncate_table(engine, table=SportsVenue)
    # load_sports_centre_mappings(engine)
    type(SportsVenue)
