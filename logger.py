import logging
import sys

LOG_FORMAT = "%(asctime)s - [%(levelname)s] %(name)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

def get_logger(name):
   logger = logging.getLogger(name)

   if not logger.handlers:
       handler = logging.StreamHandler(sys.stdout)
       handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
       logger.addHandler(handler)

   logger.setLevel(logging.DEBUG)
   return logger