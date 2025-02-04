# logger.py
from loguru import logger

# Configure the logger
logger.remove()  # Removes the default logger configuration
logger.add(sys.stdout, level="INFO")  # Adds a custom handler (e.g., stdout)
logger.add("my_logfile.log", level="DEBUG", rotation="1 week")  # Adds a file handler

# Optionally, you can customize more options like format, backtrace, and diagnose.
