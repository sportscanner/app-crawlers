import sportscanner.storage.postgres.database as db
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

