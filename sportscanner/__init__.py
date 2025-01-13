import sys
import os
from dotenv import load_dotenv
from loguru import logger as logging
from enum import Enum

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


# Check for an environment variable to determine the environment
env_file = ".env" if os.getenv("ENV") == "production" else "dev.env"
# Load the appropriate .env file
load_dotenv(dotenv_path=env_file)