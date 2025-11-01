from datetime import date, datetime, time
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel

class SortByOptions(Enum):
    distance = "distance"
    price = "price"

