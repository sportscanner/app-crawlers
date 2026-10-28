"""Gladstone Go tenant registry for the padel venues added from the UK public inventory.

Gladstone Go is the same booking engine as Mytime Active and Vision RCL, but
each operator is a separate tenant host. A venue needs the tenant host, the
site id and the padel court-hire activity id(s); all three were verified live
against the public availability API. Slugs match ``sportscanner/venues.json``.

Add a venue here when it is added to venues.json; the crawler skips venues
without an entry rather than guessing a site/activity.
"""

from typing import Dict, List, TypedDict


class GladstoneTenant(TypedDict):
    host: str
    site_id: str
    activity_ids: List[str]


GLADSTONE_TENANTS: Dict[str, GladstoneTenant] = {
    "xcite-bathgate": {
        "host": "westlothian.gladstonego.cloud",
        "site_id": "BSC",
        "activity_ids": ["BLCPTEN"],
    },
    "the-triangle-leisure-centre-places-leisure": {
        "host": "placesleisure.gladstonego.cloud",
        "site_id": "149",
        "activity_ids": ["149A001015"],
    },
    "sports-centre-and-gym-university-of-cambridge": {
        "host": "cambridgesport.gladstonego.cloud",
        "site_id": "CBU",
        "activity_ids": ["USCAPADWO02"],
    },
    "glasgow-club-scotstoun": {
        "host": "glasgowclub.gladstonego.cloud",
        "site_id": "SRSLC",
        "activity_ids": ["S0985"],
    },
    "lexus-nottingham-tennis-centre": {
        "host": "nottinghamtenniscentre.gladstonego.cloud",
        "site_id": "NTC",
        "activity_ids": ["NTCACT0301"],
    },
    "stapleford-community-pavilion": {
        "host": "lleisure.gladstonego.cloud",
        "site_id": "STA",
        "activity_ids": ["STAPAD005", "STAPAD006"],
    },
}
