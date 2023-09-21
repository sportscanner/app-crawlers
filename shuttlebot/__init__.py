import sys

from loguru import logger as logging

from shuttlebot import config

logging.remove(0)
logging.add(sys.stderr, level=config.LOGGING_LEVEL)
