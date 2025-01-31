import os
import sys
from enum import Enum

from loguru import logger as logging
from prefect import get_run_logger

class Levels(Enum):
    """Loguru log levels and severity config"""

    TRACE = 5
    DEBUG = 10
    INFO = 20
    SUCCESS = 25
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


logging.remove(0)
logging.add(sys.stderr, level=Levels.INFO.name)

# Set up Prefect's logger to work with Loguru
def setup_loguru_logging():
    try:
        # Try to get the Prefect logger only if we're in a flow run
        prefect_logger = get_run_logger()

        # If we successfully get the Prefect logger, use it with Loguru
        logging.add(prefect_logger.handlers[0], level=Levels.INFO.name)
    except Exception as e:
        # If we're not in a flow context, fall back to using basic logging
        logging.add(sys.stderr, level=Levels.INFO.name)
        logging.warning(f"Not inside a Prefect flow. Defaulting to basic logging: {e}")

