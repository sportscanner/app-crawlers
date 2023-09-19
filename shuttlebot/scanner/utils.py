import sys

import jsonschema
from loguru import logger as logging

from shuttlebot import config


def validate_json_schema(data):
    try:
        # Validate the data against the schema
        jsonschema.validate(data, config.schema)
        logging.success("JSON data is valid according to the schema")
        return True
    except jsonschema.exceptions.ValidationError as e:
        logging.error("JSON data is not valid according to the schema:")
        logging.error(e)
        return False
