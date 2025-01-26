import json
from typing import List

from loguru import logger as logging
from pydantic import ValidationError

import sportscanner.storage.postgres.database as db
from sportscanner import config


def get_venues_from_database():
    sports_centre_lists = db.get_all_rows(
        db.engine, table=db.SportsVenue, expression=db.select(db.SportsVenue)
    )
    return [
        sports_centre.venue_name for sports_centre in sports_centre_lists
    ], sports_centre_lists
