import hashlib
import json
from datetime import date, datetime, time
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, Path
from rich import print
from starlette import status
from starlette.concurrency import run_in_threadpool

import sportscanner.storage.postgres.database as db
from sportscanner.cache import cache_get_json, cache_set_json
from sportscanner.cache import get_or_load_json as cache_get_or_load_json
from sportscanner.storage.postgres.tables import (
    BadmintonMasterTable,
    SquashMasterTable,
    PickleballMasterTable,
    PadelMasterTable,
    TennisMasterTable,
    SportsVenue,
)
from sportscanner.api.routers.core.schemas import SportscannerSupportedSports
from sportscanner.api.routers.search.schemas import (
    SearchCriteria,
    SortByOptions,
    TimeFilter,
)
from sportscanner.api.routers.users.service.userService import UserService
from sportscanner.api.routers.venues.utils import (
    get_venues_near_postcode,
    normalize_postcode_for_cache_key,
)
from sportscanner.crawlers.pipeline import *
from sportscanner.storage.postgres.dataset_transform import (
    VENUE_LOOKUP_TTL_SECONDS,
    group_slots_by_attributes,
    sort_and_format_grouped_slots_for_ui,
)
from sportscanner.variables import settings

router = APIRouter()

DEFAULT_RADIUS_MILES = 10.0

# Identical searches are extremely common (the same postcode/date re-requested
# while the user flips sort, time or court type, and every user searching the
# same area). The crawl only changes every 15-40 minutes, so a short response
# cache removes the database work entirely for repeat requests without ever
# serving meaningfully stale availability.
SEARCH_CACHE_KEY_PREFIX = "search:v1:"

# Venue -> organisation mapping for "social games" venues. Near-static (it
# changes only when a venue is added), but it was re-queried on every search.
GAME_COMPOSITE_KEYS_CACHE_KEY = "game_composite_keys:v1"

_display_date_cache: dict = {}


def _price_sort_value(value: Optional[str]) -> float:
    """Numeric sort key for a display price.

    Prices can be plain ("£10.10") or pipeline estimates ("~£10.10"). The
    estimate marker must be stripped too, otherwise sorting by price raises
    ValueError and the whole search returns 500. Unknown/blank prices sort
    last instead of failing the request.
    """
    try:
        return float(str(value).replace("£", "").replace("~", "").strip())
    except (TypeError, ValueError):
        return float("inf")


def find_query_table(sport: SportscannerSupportedSports):
    if sport == SportscannerSupportedSports.BADMINTON:
        return BadmintonMasterTable
    elif sport == SportscannerSupportedSports.SQUASH:
        return SquashMasterTable
    elif sport == SportscannerSupportedSports.PICKLEBALL:
        return PickleballMasterTable
    elif sport == SportscannerSupportedSports.PADEL:
        return PadelMasterTable
    elif sport == SportscannerSupportedSports.TENNIS:
        return TennisMasterTable
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported sport category: {sport}",
        )


def _composite_key_of(row) -> str:
    """A single-column select yields sqlalchemy Row objects; some call sites and
    tests stub this out with plain strings or lightweight objects."""
    if isinstance(row, str):
        return row
    key = getattr(row, "composite_key", None)
    if key is not None:
        return key
    return row[0]


def _load_game_composite_keys() -> List[str]:
    """Social games (per-person sessions like Lemon Pickleball) are not court
    bookings, so they are excluded from court search and served via /games."""
    from sportscanner.api.routers.games.endpoints import GAMES_ORGANISATIONS

    rows = db.get_all_rows(
        db.engine,
        None,
        db.select(SportsVenue.composite_key).where(
            SportsVenue.organisation.in_(GAMES_ORGANISATIONS)
        ),
    )
    return [_composite_key_of(row) for row in rows]


def get_game_composite_keys() -> set:
    return set(
        cache_get_or_load_json(
            GAME_COMPOSITE_KEYS_CACHE_KEY,
            _load_game_composite_keys,
            VENUE_LOOKUP_TTL_SECONDS,
        )
    )


def _search_cache_key(
    sport: SportscannerSupportedSports,
    search_date: date,
    filters: SearchCriteria,
    radius: float,
    time_range: TimeFilter,
    sort_by: SortByOptions,
) -> str:
    """Stable key for one search request. Every input that changes the response
    is included, and nothing that does not (so two equivalent postcodes such as
    "se18ul" and "SE1 8UL" share one entry)."""
    analytics = filters.analytics
    payload = {
        "sport": sport.value,
        "date": search_date.isoformat(),
        "postcode": normalize_postcode_for_cache_key(filters.postcode or ""),
        "radius": round(float(radius), 2),
        "from": time_range.starting.isoformat(),
        "to": time_range.ending.isoformat(),
        "sortBy": sort_by.value,
        "indoor": filters.indoor,
        # Whole analytics block, including the flags the query layer currently
        # ignores: safer to over-key than to serve a stale body if they start
        # affecting results later.
        "analytics": (
            {
                "consecutiveSlots": analytics.consecutiveSlots,
                "preferredLocations": analytics.searchUserPreferredLocations,
                "venues": (
                    sorted(analytics.specifiedVenues)
                    if analytics.specifiedVenues
                    else None
                ),
            }
            if analytics
            else None
        ),
    }
    digest = hashlib.blake2b(
        json.dumps(payload, sort_keys=True).encode("utf-8"), digest_size=16
    ).hexdigest()
    return f"{SEARCH_CACHE_KEY_PREFIX}{digest}"


def _parse_display_date(label: str) -> datetime:
    """`sort_and_format_grouped_slots_for_ui` emits labels like "Wed, Nov 04".
    Cache the parse: a wide-radius search has many groups but few distinct
    dates, and strptime is comparatively expensive."""
    parsed = _display_date_cache.get(label)
    if parsed is None:
        parsed = datetime.strptime(label, "%a, %b %d")
        _display_date_cache[label] = parsed
    return parsed


def _sort_response(rows: List[dict], sort_by: SortByOptions) -> List[dict]:
    """Sort by the requested field, never failing the whole response on one
    unparseable value."""

    def sort_key(row: dict):
        value = row.get(sort_by.name)
        if sort_by is SortByOptions.price:
            value = _price_sort_value(value)
        return (_parse_display_date(row["date"]), value)

    return sorted(rows, key=sort_key)


def _build_search_response(
    query_table,
    composite_keys: List[str],
    search_date: date,
    time_range: TimeFilter,
    indoor: Optional[bool],
    sort_by: SortByOptions,
    distance_from_venues_reference: dict,
    game_composite_keys: set,
) -> List[dict]:
    """Everything that touches Postgres or burns CPU for a search, kept in one
    function so the whole block can run off the event loop."""
    composite_keys = [key for key in composite_keys if key not in game_composite_keys]
    if not composite_keys:
        return []

    query = (
        db.select(query_table)
        .where(query_table.composite_key.in_(composite_keys))
        .where(query_table.spaces > 0)  # Ignore empty courts
        .where(query_table.starting_time >= time_range.starting)
        .where(query_table.ending_time <= time_range.ending)
        .where(query_table.date == search_date)
        .where(query_table.starts_at > datetime.now())
    )
    # `indoor` only exists on the padel/tennis/pickleball tables (see
    # ensure_indoor_column) - badminton/squash have no such column.
    if indoor is not None and hasattr(query_table, "indoor"):
        query = query.where(query_table.indoor == indoor)

    slots = db.get_all_rows(db.engine, None, query)
    grouped_slots = group_slots_by_attributes(
        slots, attributes=("composite_key", "date")
    )
    formatted = sort_and_format_grouped_slots_for_ui(
        grouped_slots, distance_from_venues_reference
    )
    return _sort_response(formatted, sort_by)


@router.post("/{sport}", operation_id="search_search__sport__post")
async def search_courts(
    sport: SportscannerSupportedSports = Path(
        description="Sport category to filter venues and court availability"
    ),
    date: date = Query(..., description="Date to filter court availability"),
    filters: SearchCriteria = ...,
):
    """Returns all court availability relevant to specified filters passed via payload"""
    queryTable = find_query_table(sport)

    # Optional fields are normalised once here rather than dotted through the
    # query builder, so a payload that omits `timeRange`/`analytics` behaves
    # like the documented defaults instead of raising AttributeError.
    analytics = filters.analytics
    specified_venues = analytics.specifiedVenues if analytics else None
    time_range = filters.timeRange or TimeFilter(
        starting=time(0, 0), ending=time(23, 59)
    )
    # `sortBy` is declared Optional[SortByOptions] but defaults to a bare string,
    # and Pydantic does not validate defaults, so an omitted sortBy arrives as
    # "distance" rather than the enum member. Normalise it.
    sort_by = (
        SortByOptions(filters.sortBy) if filters.sortBy else SortByOptions.distance
    )
    radius = filters.radius if filters.radius is not None else DEFAULT_RADIUS_MILES

    if not filters.postcode:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A postcode is required to search court availability.",
        )

    cache_key = _search_cache_key(
        sport=sport,
        search_date=date,
        filters=filters,
        radius=radius,
        time_range=time_range,
        sort_by=sort_by,
    )
    cached = await run_in_threadpool(cache_get_json, cache_key)
    if cached is not None:
        return cached

    try:
        nearby_venues = await get_venues_near_postcode(filters.postcode, radius)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to fetch metadata - {filters.postcode} is not a valid UK postcode. Try changing the postcode to another one.",
        )

    if specified_venues:
        composite_keys: List[str] = list(specified_venues)
    else:
        composite_keys = [venue.composite_key for venue in nearby_venues]

    distance_from_venues_reference = {
        venue.composite_key: venue.distance for venue in nearby_venues
    }

    game_composite_keys = await run_in_threadpool(get_game_composite_keys)

    # Blocking psycopg2 work plus the grouping/formatting pass. This handler is
    # `async def` (the MCP search tool awaits it directly), and uvicorn runs a
    # single event loop per worker: doing this inline froze the whole process,
    # so concurrent searches queued behind each other (measured: 0.6s alone,
    # 4-8s with eight in flight, and health checks stalled for 3s+).
    sorted_response = await run_in_threadpool(
        _build_search_response,
        queryTable,
        composite_keys,
        date,
        time_range,
        filters.indoor,
        sort_by,
        distance_from_venues_reference,
        game_composite_keys,
    )

    await run_in_threadpool(
        cache_set_json,
        cache_key,
        sorted_response,
        settings.SEARCH_CACHE_TTL_SECONDS,
    )
    return sorted_response


@router.post(
    "/{sport}/{composite_key}",
    operation_id="search_search__sport___composite_key__post",
)
def search_venue_courts(
    sport: SportscannerSupportedSports = Path(
        description="Sport category to filter venues and court availability"
    ),
    date: date = Query(..., description="Date to filter court availability"),
    composite_key: str = Path(
        ..., description="Composite key identifier to filter venue court availability"
    ),
):
    queryTable = find_query_table(sport)

    current_timestamp = datetime.now()

    # `def` (not `async def`) so FastAPI runs this blocking query in its
    # threadpool instead of on the event loop.
    return db.get_all_rows(
        db.engine,
        None,
        db.select(queryTable)
        .where(queryTable.composite_key == composite_key)
        .where(queryTable.spaces > 0)  # Ignore empty courts
        .where(queryTable.date == date)
        .where(queryTable.starts_at > current_timestamp),
    )
