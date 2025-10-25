# logging.py
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

LOGGING_LEVEL = Levels.INFO.value

logging.remove(0)
logging.add(sys.stdout, level=LOGGING_LEVEL)

# Optionally, you can customize more options like format, backtrace, and diagnose.
