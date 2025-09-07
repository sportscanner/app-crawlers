import os
import sys
from enum import Enum

from loguru import logger as logging


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
logging.add(sys.stderr, level=Levels.DEBUG.name)
