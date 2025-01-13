import sportscanner.storage.postgres.database as db
from sportscanner.config import SportsVenueMappingSchema
from typing import List
from sportscanner import config
import json
from loguru import logger as logging
from pydantic import ValidationError


def get_venues_from_database():
    sports_centre_lists = db.get_all_rows(
        db.engine, table=db.SportsVenue, expression=db.select(db.SportsVenue)
    )
    return [
        sports_centre.venue_name for sports_centre in sports_centre_lists
    ], sports_centre_lists


def get_venues_from_raw() -> List[SportsVenueMappingSchema]:
    """Loads sports centre lookup sheet to Table: SportsVenue"""
    with open(f"./{config.MAPPINGS}", "r") as file:
        raw_sports_centres = json.load(file)
        try:
            sports_centre_lists: List[SportsVenueMappingSchema] = [
                SportsVenueMappingSchema(**item) for item in raw_sports_centres
            ]
            logging.success("JSON data is valid according to the Pydantic model!")
            return sports_centre_lists
        except ValidationError as error:
            logging.error(
                f"JSON data is not valid according to the Pydantic model:\n {error}"
            )
            raise RuntimeError


