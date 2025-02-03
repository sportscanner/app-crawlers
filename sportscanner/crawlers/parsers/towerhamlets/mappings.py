from dataclasses import dataclass
from typing import List, Tuple
import itertools
from rich import print
from sportscanner.storage.postgres.database import SportsVenue

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
    "JOSC": ["JACT000010", "JACT000011"],
    "WSC": ["WACT000010", "WACT000011"],
    "PBLC": ["PACT000010", "PACT000011"],
    "MEPLS": ["MACT000009", "MACT000010", "MACT000011"]
}

siteIdsActivityIds: List[HyperlinkGenerator] = [HyperlinkGenerator(siteId=key, activityId=activity) for key, activities in activityIds.items() for activity in activities]

if __name__  == "__main__":
    print(siteIdsActivityIds)
