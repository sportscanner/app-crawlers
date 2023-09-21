import sys

from loguru import logger as logging

from shuttlebot import config

logging.remove(0)


def init_logger():
    logging.add(sys.stderr, level=config.LOGGING_LEVEL)
    return logging
