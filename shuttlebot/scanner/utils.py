import sys
from time import time

import jsonschema
from loguru import logger as logging

from shuttlebot import config


def validate_json_schema(data):
    """Validates the Location and alias mapping inputs against a defined schema"""
    try:
        # Validate the data against the schema
        jsonschema.validate(data, config.schema)
        logging.success("JSON data is valid according to the schema")
        return True
    except jsonschema.exceptions.ValidationError as e:
        logging.error("JSON data is not valid according to the schema:")
        logging.error(e)
        return False


def timeit(func):
    """Decorator to calculate function runtime"""
    def wrap_func(*args, **kwargs):
        tic = time()
        result = func(*args, **kwargs)
        tac = time()
        logging.info(f"Function {func.__name__!r} executed in {(tac - tic):.4f}s")
        return result

    return wrap_func
