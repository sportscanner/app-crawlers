import itertools
import json
from datetime import date, datetime, time, timedelta
from functools import wraps
from time import time as timer
from typing import List, Optional

from loguru import logger as logging
from pydantic import BaseModel, ValidationError
from rich import print
from sqlmodel import select

from sportscanner import config, schemas


def timeit(func):
    """Calculates the execution time of the function on top of which the decorator is assigned"""

    @wraps(func)
    def wrap_func(*args, **kwargs):
        tic = timer()
        result = func(*args, **kwargs)
        tac = timer()
        logging.info(f"Function {func.__name__!r} executed in {(tac - tic):.4f}s")
        return result

    return wrap_func


def async_timer(func):
    """Calculates the execution time of the Async function on top of which the decorator is assigned"""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        tic = timer()
        result = await func(*args, **kwargs)
        tac = timer()
        logging.debug(f"Function {func.__name__!r} executed in {(tac - tic):.4f}s")
        return result

    return wrapper


def get_sports_venue_mappings_from_raw(path: str = "./sportscanner/venues.json",) -> schemas.SportsVenueMappingModel:
    with open(path, "r") as file:
        raw_sports_centres = json.load(file)
        try:
            sports_centre_lists: schemas.SportsVenueMappingModel = (
                schemas.SportsVenueMappingModel(root=raw_sports_centres)
            )
            logging.success("JSON data is valid according to the Pydantic model!")
            return sports_centre_lists
        except ValidationError as error:
            logging.error(
                f"JSON data is not valid according to the Pydantic model:\n {error}"
            )
            raise RuntimeError


if __name__ == "__main__":
    """Write a test here for calculating consecutive slots"""
    logging.info("Attempting load of raw mappings from json file")
    _tmp: schemas.SportsVenueMappingModel = get_sports_venue_mappings_from_raw()
    print(_tmp)
