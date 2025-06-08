import itertools
from dataclasses import dataclass
from typing import List, Tuple

from rich import print

from sportscanner.storage.postgres.tables import SportsVenue


@dataclass
class HyperlinkGenerator:
    siteId: str
    activityId: str


@dataclass
class Parameters:
    siteId: str
    activityId: str
    venue: SportsVenue


activityIds: dict[str, list[str]] = {
    "CAS": ["CAACT00001"]
}

siteIdsActivityIds: List[HyperlinkGenerator] = [
    HyperlinkGenerator(siteId=key, activityId=activity)
    for key, activities in activityIds.items()
    for activity in activities
]

if __name__ == "__main__":
    print(siteIdsActivityIds)
