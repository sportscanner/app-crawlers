"""Matchpoint (TPC-MatchPoint) tenant registry.

Each club is a separate ASP.NET WebForms tenant on ``{host}.matchpoint.com.es``.
The availability grid id (``idCuadro``) is the tenant's padel/location grid:
most tenants expose padel as grid 4, while the multi-location PadelStars tenant
has one grid per venue. Slugs match ``sportscanner/venues.json``.

Add a venue here when it is added to venues.json; the crawler skips venues
without an entry rather than guessing a grid.
"""

from typing import Dict, TypedDict


class MatchpointTenant(TypedDict):
    host: str
    grid_id: int


MATCHPOINT_TENANTS: Dict[str, MatchpointTenant] = {
    # Existing Stratford venue (kept here for the complete provider registry).
    "stratford-padel-club": {
        "host": "stratfordpadelclub.matchpoint.com.es",
        "grid_id": 4,
    },
    "the-heron-padel-club": {
        "host": "theheronpadelclub-gb.matchpoint.com.es",
        "grid_id": 4,
    },
    "bromley-sports-club": {
        "host": "bromleysportsclub-gb.matchpoint.com.es",
        "grid_id": 4,
    },
    "acorn-padel-club": {
        "host": "acornpadelclub-ie.matchpoint.com.es",
        "grid_id": 4,
    },
    "padelstars-guildford": {
        "host": "padelstars-gb.matchpoint.com.es",
        "grid_id": 17,
    },
    "padelstars-taunton": {
        "host": "padelstars-gb.matchpoint.com.es",
        "grid_id": 14,
    },
    "zing-padel-hemel-hempstead": {
        "host": "zingpadel-gb.matchpoint.com.es",
        "grid_id": 4,
    },
    "marden-cricket-and-hockey-club": {
        "host": "mardensportsclub-gb.matchpoint.com.es",
        "grid_id": 4,
    },
}
