"""Borough reference data: ONS populations and venue-to-borough resolution."""

import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import httpx

from sportscanner.logger import logging

_POPULATION_FILE = Path(__file__).parent / "data" / "london_borough_population.json"
_POSTCODES_IO_BULK_REVERSE = "https://api.postcodes.io/postcodes"
_POSTCODES_IO_BATCH = 100
_BOROUGH_CACHE_TTL_SECONDS = 24 * 60 * 60

OUTSIDE_LONDON = "Outside London"


def borough_slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def borough_name(slug: str) -> Optional[str]:
    return next((name for name in borough_population()["boroughs"] if borough_slug(name) == slug), None)

# composite_key -> (borough or None, cached_at). Venues don't move, so a failed
# lookup is retried on the next refresh rather than cached as "unknown" forever.
_borough_cache: Dict[str, Tuple[Optional[str], float]] = {}


@lru_cache(maxsize=1)
def borough_population() -> dict:
    """{"year": int, "source": str, "boroughs": {name: {"code", "population"}}}."""
    with open(_POPULATION_FILE) as f:
        return json.load(f)


def london_population() -> int:
    return sum(b["population"] for b in borough_population()["boroughs"].values())


def normalise_borough(district: Optional[str]) -> Optional[str]:
    """Maps a postcodes.io `admin_district` to a London borough name, or
    OUTSIDE_LONDON for commuter-belt venues (Waltham Abbey, Weybridge, ...)."""
    if not district:
        return None
    return district if district in borough_population()["boroughs"] else OUTSIDE_LONDON


def resolve_boroughs(venues: Iterable[Tuple[str, float, float]]) -> Dict[str, Optional[str]]:
    """Resolves (composite_key, latitude, longitude) to borough names via the
    postcodes.io bulk reverse-geocoder, cached in-process for a day.

    Coordinates rather than postcodes, because several venues have no postcode
    in venues.json. Unresolvable venues map to None and are grouped as unknown.
    """
    venues = list(venues)
    now = time.time()
    pending = [
        v for v in venues
        if v[1] is not None and v[2] is not None and (
            v[0] not in _borough_cache or _borough_cache[v[0]][0] is None
            or now - _borough_cache[v[0]][1] > _BOROUGH_CACHE_TTL_SECONDS
        )
    ]
    for start in range(0, len(pending), _POSTCODES_IO_BATCH):
        batch = pending[start:start + _POSTCODES_IO_BATCH]
        payload = {
            "geolocations": [
                {"longitude": lon, "latitude": lat, "limit": 1, "radius": 2000}
                for _, lat, lon in batch
            ]
        }
        try:
            response = httpx.post(_POSTCODES_IO_BULK_REVERSE, json=payload, timeout=20)
            response.raise_for_status()
            results = response.json().get("result") or []
        except Exception as exc:
            logging.warning(f"Borough lookup failed for {len(batch)} venues: {exc!r}")
            continue
        for (key, _, _), item in zip(batch, results):
            matches = (item or {}).get("result") or []
            district = matches[0].get("admin_district") if matches else None
            _borough_cache[key] = (normalise_borough(district), now)

    return {key: _borough_cache.get(key, (None, 0))[0] for key, _, _ in venues}
