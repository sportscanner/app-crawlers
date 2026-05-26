"""
SportScanner API MCP tools.

Each tool in this module wraps a public SportScanner API endpoint so an MCP
client can interact with the API using typed parameters and rich metadata.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
from datetime import date, time
from typing import Annotated, Any, Dict, List, Literal, Optional

import httpx
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field, model_validator

try:
    from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes

    _OI_SPAN_KIND_KEY = SpanAttributes.OPENINFERENCE_SPAN_KIND
    _OI_TOOL_SPAN_KIND = OpenInferenceSpanKindValues.TOOL.value
except Exception:
    _OI_SPAN_KIND_KEY = None
    _OI_TOOL_SPAN_KIND = None

from sportscanner.variables import settings

SupportedSport = Literal["badminton", "squash", "pickleball", "padel"]
SupportedSortBy = Literal["distance", "price"]
_tracer = trace.get_tracer(__name__)
_LOCATION_WITHIN_OF_RE = re.compile(
    r"\bwithin\s+\d+(?:\.\d+)?\s*(?:mile|miles|mi|km|kms|kilometres?|kilometers?)\s+of\s+",
    re.IGNORECASE,
)
_LOCATION_NEAR_PREFIX_RE = re.compile(
    r"^(?:near|around|close to|in|at)\s+",
    re.IGNORECASE,
)


class SearchTimeRange(BaseModel):
    """Time window for slot search."""

    starting: time = Field(
        ...,
        description="Start of the requested time window in 24-hour format, e.g. 18:00:00.",
    )
    ending: time = Field(
        ...,
        description="End of the requested time window in 24-hour format, e.g. 22:00:00.",
    )

    @model_validator(mode="after")
    def validate_time_window(self) -> "SearchTimeRange":
        if self.starting >= self.ending:
            raise ValueError("'starting' must be earlier than 'ending'.")
        return self


class SearchAnalyticsFilters(BaseModel):
    """Optional advanced search analytics used by the backend search endpoint."""

    consecutiveSlots: Optional[int] = Field(
        default=None,
        ge=1,
        description="Optional minimum number of consecutive slots to look for.",
    )
    searchUserPreferredLocations: bool = Field(
        default=False,
        description="If true, prioritize user-preferred venues when supported.",
    )
    specifiedVenues: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional list of venue composite keys. If supplied, search is limited "
            "to these venues only."
        ),
    )


class SearchFilters(BaseModel):
    """Payload for `POST /search/{sport}`."""

    postcode: str = Field(
        ...,
        min_length=2,
        description="UK postcode used as the search origin for nearby venues.",
    )
    radius: float = Field(
        default=10.0,
        gt=0,
        le=100,
        description="Search radius in miles.",
    )
    timeRange: SearchTimeRange = Field(
        ...,
        description="Required time window to filter returned slots.",
    )
    analytics: SearchAnalyticsFilters = Field(
        default_factory=SearchAnalyticsFilters,
        description="Optional advanced filters and venue pinning controls.",
    )
    sortBy: SupportedSortBy = Field(
        default="distance",
        description="Sort grouped venue results by `distance` or `price`.",
    )


class UserProfileUpdatePayload(BaseModel):
    """Payload for `PATCH /user/`."""

    onboarding: Optional[bool] = Field(
        default=None,
        description="Optional onboarding completion flag.",
    )
    preferences: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Flexible preference dictionary (for example postcode, searchRadius, "
            "preferredVenues, preferredTimes, goals, skills, availability)."
        ),
    )

    @model_validator(mode="after")
    def validate_not_empty(self) -> "UserProfileUpdatePayload":
        if self.onboarding is None and not self.preferences:
            raise ValueError(
                "At least one of 'onboarding' or non-empty 'preferences' is required."
            )
        return self


class CreateNotificationPayload(BaseModel):
    """Payload for `POST /notifications/admin`."""

    title: str = Field(..., min_length=1, description="Notification title.")
    message: str = Field(..., min_length=1, description="Notification message body.")
    active: bool = Field(
        default=True,
        description="Whether the notification is active immediately.",
    )


class UpdateNotificationPayload(BaseModel):
    """Payload for `PATCH /notifications/admin/{notification_id}`."""

    title: Optional[str] = Field(default=None, description="Updated title.")
    message: Optional[str] = Field(default=None, description="Updated message body.")
    active: Optional[bool] = Field(
        default=None,
        description="Set to false to hide notification globally.",
    )

    @model_validator(mode="after")
    def validate_not_empty(self) -> "UpdateNotificationPayload":
        if self.title is None and self.message is None and self.active is None:
            raise ValueError(
                "At least one of 'title', 'message', or 'active' is required."
            )
        return self


def _get_api_base_url() -> str:
    configured = os.getenv("SPORTSCANNER_MCP_API_BASE_URL") or settings.API_BASE_URL
    return configured.rstrip("/")


async def _sportscanner_api_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    authorization: Optional[str] = None,
    timeout_seconds: float = 30.0,
) -> Any:
    """
    Execute an HTTP request against the SportScanner API and normalize errors.
    """
    base_url = _get_api_base_url()
    normalized_path = path if path.startswith("/") else f"/{path}"
    url = f"{base_url}{normalized_path}"
    current_frame = inspect.currentframe()
    caller = current_frame.f_back if current_frame else None
    caller_name = caller.f_code.co_name if caller else "unknown_tool"
    del current_frame
    del caller

    headers: Dict[str, str] = {"Accept": "application/json"}
    if authorization:
        headers["Authorization"] = authorization

    with _tracer.start_as_current_span("sportscanner.mcp.api_request") as span:
        if _OI_SPAN_KIND_KEY and _OI_TOOL_SPAN_KIND:
            span.set_attribute(_OI_SPAN_KIND_KEY, _OI_TOOL_SPAN_KIND)
        span.set_attribute("sportscanner.api.method", method.upper())
        span.set_attribute("sportscanner.api.path", normalized_path)
        span.set_attribute("sportscanner.api.base_url", base_url)
        span.set_attribute("sportscanner.mcp.tool_name", caller_name)
        span.set_attribute("sportscanner.api.has_params", bool(params))
        span.set_attribute("sportscanner.api.has_json_body", bool(json_body))
        span.set_attribute("sportscanner.api.has_authorization", bool(authorization))

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=headers,
                params=params,
                json=json_body,
            )

        span.set_attribute("http.status_code", response.status_code)

        if response.status_code == 204:
            return {"success": True, "status_code": 204}

        try:
            payload: Any = response.json()
        except ValueError:
            payload = response.text

        if response.status_code >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            message = (
                f"SportScanner API request failed ({response.status_code}) for "
                f"{method.upper()} {normalized_path}: {detail}"
            )
            span.set_status(Status(StatusCode.ERROR, message))
            raise ValueError(message)

        span.set_status(Status(StatusCode.OK))
        return payload


async def get_api_root() -> Dict[str, Any]:
    """
    Get API metadata from `GET /`.

    Useful for checking API identity, version, and top-level advertised actions.
    """
    response = await _sportscanner_api_request("GET", "/")
    if not isinstance(response, dict):
        raise ValueError("Unexpected root response format from SportScanner API.")
    return response


async def search_sport_availability(
    sport: Annotated[
        SupportedSport,
        Field(
            description=(
                "Sport category to search (`badminton`, `squash`, `pickleball`, "
                "or `padel`)."
            )
        ),
    ],
    search_date: Annotated[
        date,
        Field(description="Date to search in YYYY-MM-DD format."),
    ],
    filters: Annotated[
        SearchFilters,
        Field(
            description=(
                "Search filters mapped directly to the API body of "
                "`POST /search/{sport}`."
            )
        ),
    ],
) -> List[Dict[str, Any]]:
    """
    Call `POST /search/{sport}?date=YYYY-MM-DD` to fetch grouped court slots.
    """
    response = await _sportscanner_api_request(
        method="POST",
        path=f"/search/{sport}",
        params={"date": search_date.isoformat()},
        json_body=filters.model_dump(mode="json", exclude_none=True),
    )
    if not isinstance(response, list):
        raise ValueError("Unexpected response format for search_sport_availability.")
    return response


async def search_single_venue_availability(
    sport: Annotated[
        SupportedSport,
        Field(description="Sport category for this venue-specific slot lookup."),
    ],
    composite_key: Annotated[
        str,
        Field(
            min_length=1,
            description=(
                "Venue composite key (8-char hash used by SportScanner). "
                "Obtain it from sportscanner_find_venues_near_location_query "
                "or sportscanner_find_venues_near_postcode results."
            ),
        ),
    ],
    search_date: Annotated[
        date,
        Field(description="Date to search in YYYY-MM-DD format."),
    ],
) -> List[Dict[str, Any]]:
    """
    Call `POST /search/{sport}/{composite_key}?date=YYYY-MM-DD`.

    Returns ALL available slots for the given venue and date with NO time-range
    filter applied — use this tool when querying a specific named venue so that
    morning, afternoon, and evening slots are all included in the response.
    """
    response = await _sportscanner_api_request(
        method="POST",
        path=f"/search/{sport}/{composite_key}",
        params={"date": search_date.isoformat()},
    )
    if not isinstance(response, list):
        raise ValueError(
            "Unexpected response format for search_single_venue_availability."
        )
    return response


async def list_venues(
    limit: Annotated[
        Optional[int],
        Field(
            default=None,
            ge=1,
            description="Optional maximum number of venues to return.",
        ),
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Call `GET /venues/` to list venues known to SportScanner.
    """
    params = {"limit": limit} if limit is not None else None
    response = await _sportscanner_api_request("GET", "/venues/", params=params)
    if not isinstance(response, list):
        raise ValueError("Unexpected response format for list_venues.")
    return response


async def list_venues_by_sport(
    sport: Annotated[
        SupportedSport,
        Field(description="Sport category used to filter the venue catalog."),
    ],
    limit: Annotated[
        Optional[int],
        Field(
            default=None,
            ge=1,
            description="Optional maximum number of venues to return.",
        ),
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Call `GET /venues/sports/{sport}` to list venues offering one sport.
    """
    params = {"limit": limit} if limit is not None else None
    response = await _sportscanner_api_request(
        method="GET",
        path=f"/venues/sports/{sport}",
        params=params,
    )
    if not isinstance(response, list):
        raise ValueError("Unexpected response format for list_venues_by_sport.")
    return response


async def find_venues_near_postcode(
    postcode: Annotated[
        str,
        Field(
            min_length=2,
            description="UK postcode to center the radius search around.",
        ),
    ],
    distance_miles: Annotated[
        float,
        Field(
            default=10.0,
            gt=0,
            le=100,
            description="Radius in miles for nearby venue matching.",
        ),
    ] = 10.0,
) -> List[Dict[str, Any]]:
    """
    Call `GET /venues/near?postcode=&distance=` to find nearby venues.
    """
    response = await _sportscanner_api_request(
        method="GET",
        path="/venues/near",
        params={"postcode": postcode, "distance": distance_miles},
    )
    if not isinstance(response, list):
        raise ValueError("Unexpected response format for find_venues_near_postcode.")
    return response


async def get_venue_by_composite_key(
    composite_key: Annotated[
        str,
        Field(
            min_length=1,
            description="Venue composite key to resolve full venue details.",
        ),
    ],
) -> List[Dict[str, Any]]:
    """
    Call `GET /venues/{composite_key}`.
    """
    response = await _sportscanner_api_request("GET", f"/venues/{composite_key}")
    if not isinstance(response, list):
        raise ValueError("Unexpected response format for get_venue_by_composite_key.")
    return response


async def validate_postcode(
    postcode: Annotated[
        str,
        Field(min_length=2, description="Raw postcode to validate."),
    ],
) -> Dict[str, Any]:
    """
    Call `GET /geolocation/validate-postcode`.
    """
    response = await _sportscanner_api_request(
        method="GET",
        path="/geolocation/validate-postcode",
        params={"postcode": postcode},
    )
    if not isinstance(response, dict):
        raise ValueError("Unexpected response format for validate_postcode.")
    return response


async def get_postcode_metadata(
    postcode: Annotated[
        str,
        Field(min_length=2, description="Raw postcode for metadata lookup."),
    ],
) -> Dict[str, Any]:
    """
    Call `GET /geolocation/metadata-postcode`.
    """
    response = await _sportscanner_api_request(
        method="GET",
        path="/geolocation/metadata-postcode",
        params={"postcode": postcode},
    )
    if not isinstance(response, dict):
        raise ValueError("Unexpected response format for get_postcode_metadata.")
    return response


async def autocomplete_postcode(
    query: Annotated[
        str,
        Field(
            min_length=1,
            description="Partial postcode fragment used for autocomplete.",
        ),
    ],
) -> List[str]:
    """
    Call `GET /geolocation/autocomplete?q=...`.
    """
    response = await _sportscanner_api_request(
        method="GET",
        path="/geolocation/autocomplete",
        params={"q": query},
    )
    if not isinstance(response, list):
        raise ValueError("Unexpected response format for autocomplete_postcode.")
    return response


async def reverse_geocode_to_postcode(
    latitude: Annotated[
        float,
        Field(description="Latitude coordinate."),
    ],
    longitude: Annotated[
        float,
        Field(description="Longitude coordinate."),
    ],
) -> Dict[str, Any]:
    """
    Call `GET /geolocation/reverse?lat=&lon=` to get nearest postcode.
    """
    response = await _sportscanner_api_request(
        method="GET",
        path="/geolocation/reverse",
        params={"lat": latitude, "lon": longitude},
    )
    if not isinstance(response, dict):
        raise ValueError("Unexpected response format for reverse_geocode_to_postcode.")
    return response


async def resolve_location_query(
    query: Annotated[
        str,
        Field(
            min_length=1,
            description=(
                "Flexible UK location query such as a full postcode (`SW1A 1AA`), "
                "outcode/district (`E14`), or London place name (`Paddington`)."
            ),
        ),
    ],
) -> Dict[str, Any]:
    """
    Call `GET /geolocation/resolve-location?q=...`.

    Resolves partial postcode or place-name input into a full postcode and
    coordinates that can be used for proximity search tools.
    """
    response = await _sportscanner_api_request(
        method="GET",
        path="/geolocation/resolve-location",
        params={"q": query},
    )
    if not isinstance(response, dict):
        raise ValueError("Unexpected response format for resolve_location_query.")
    return response


def _normalize_location_query_text(query: str) -> str:
    cleaned = " ".join(query.strip().split())
    if not cleaned:
        return ""

    without_distance_phrase = _LOCATION_WITHIN_OF_RE.sub("", cleaned)
    without_near_prefix = _LOCATION_NEAR_PREFIX_RE.sub("", without_distance_phrase)
    normalized = without_near_prefix.strip(" ,.;:!?")
    return normalized or cleaned.strip(" ,.;:!?")


def _nominatim_geocode(query: str) -> Optional[Dict[str, Any]]:
    """
    Resolve a place name to coordinates using Nominatim as a best-effort fallback.
    """
    try:
        from geopy.geocoders import Nominatim

        geolocator = Nominatim(user_agent="sportscanner-mcp-geocoder")

        candidates = [query]
        lowered = query.lower()
        if "london" not in lowered:
            candidates.insert(0, f"{query}, London, UK")
        if "uk" not in lowered:
            candidates.append(f"{query}, UK")

        seen = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            location = geolocator.geocode(candidate, timeout=10)
            if not location:
                continue
            return {
                "display_name": location.address,
                "latitude": float(location.latitude),
                "longitude": float(location.longitude),
            }
    except Exception:
        return None

    return None


async def _resolve_postcode_via_nominatim(query: str) -> Optional[Dict[str, Any]]:
    geocoded = await asyncio.to_thread(_nominatim_geocode, query)
    if not geocoded:
        return None

    reverse_lookup = await reverse_geocode_to_postcode(
        latitude=geocoded["latitude"],
        longitude=geocoded["longitude"],
    )
    postcode = (
        reverse_lookup.get("postcode")
        if isinstance(reverse_lookup, dict)
        else None
    )
    if not postcode:
        return None

    return {
        "query": query,
        "resolved_postcode": postcode,
        "source": "place_geocode_fallback",
        "display_name": geocoded.get("display_name"),
        "latitude": geocoded.get("latitude"),
        "longitude": geocoded.get("longitude"),
        "suggestions": [geocoded.get("display_name")] if geocoded.get("display_name") else [],
    }


async def find_venues_near_location_query(
    location_query: Annotated[
        str,
        Field(
            min_length=1,
            description=(
                "Flexible location query (postcode, partial postcode like `E14`, "
                "or London place name like `Paddington`)."
            ),
        ),
    ],
    distance_miles: Annotated[
        float,
        Field(
            default=10.0,
            gt=0,
            le=100,
            description="Radius in miles for nearby venue matching.",
        ),
    ] = 10.0,
) -> Dict[str, Any]:
    """
    Resolve flexible location text, then call `GET /venues/near`.

    This is a convenience tool for natural-language location queries where users
    provide an outcode or place name instead of a full postcode.

    This tool does not raise on unresolved input; instead it returns
    `resolved=false` with an explanatory message and empty `venues`.
    """
    normalized_query = _normalize_location_query_text(location_query)

    resolved_location = await resolve_location_query(location_query)
    if (
        not resolved_location.get("resolved_postcode")
        and normalized_query
        and normalized_query != location_query
    ):
        normalized_resolution = await resolve_location_query(normalized_query)
        if normalized_resolution.get("resolved_postcode"):
            resolved_location = normalized_resolution

    if not resolved_location.get("resolved_postcode"):
        geocode_resolution = await _resolve_postcode_via_nominatim(normalized_query)
        if geocode_resolution is not None:
            resolved_location = geocode_resolution

    resolved_postcode = resolved_location.get("resolved_postcode")
    if not resolved_postcode:
        message = resolved_location.get("message") or (
            "Could not resolve that location into a postcode."
        )
        return {
            "query": location_query,
            "normalized_query": normalized_query,
            "resolved": False,
            "message": message,
            "resolved_location": resolved_location,
            "distance_miles": distance_miles,
            "venues": [],
        }

    nearby_venues = await find_venues_near_postcode(
        postcode=resolved_postcode,
        distance_miles=distance_miles,
    )
    return {
        "query": location_query,
        "normalized_query": normalized_query,
        "resolved": True,
        "resolved_location": resolved_location,
        "distance_miles": distance_miles,
        "venues": nearby_venues,
    }


async def get_scrapers_health(
    sport: Annotated[
        SupportedSport,
        Field(
            description=(
                "Sport/table to check for scraper refresh health "
                "(`badminton`, `squash`, `pickleball`, `padel`)."
            )
        ),
    ],
) -> List[Dict[str, Any]]:
    """
    Call `GET /health/scrapers?sports={sport}`.
    """
    response = await _sportscanner_api_request(
        method="GET",
        path="/health/scrapers",
        params={"sports": sport},
    )
    if not isinstance(response, list):
        raise ValueError("Unexpected response format for get_scrapers_health.")
    return response


async def get_user_profile(
    authorization: Annotated[
        str,
        Field(
            min_length=1,
            description=(
                "Value sent as the `Authorization` header. This API expects the "
                "Kinde refresh token value used by existing SportScanner clients."
            ),
        ),
    ],
) -> Dict[str, Any]:
    """
    Call `GET /user/` for the authenticated user.
    """
    response = await _sportscanner_api_request(
        method="GET",
        path="/user/",
        authorization=authorization,
    )
    if not isinstance(response, dict):
        raise ValueError("Unexpected response format for get_user_profile.")
    return response


async def register_user(
    authorization: Annotated[
        str,
        Field(
            min_length=1,
            description="Authorization header value (Kinde refresh token).",
        ),
    ],
) -> Dict[str, Any]:
    """
    Call `POST /user/` to create/register a user profile.
    """
    response = await _sportscanner_api_request(
        method="POST",
        path="/user/",
        authorization=authorization,
    )
    if not isinstance(response, dict):
        raise ValueError("Unexpected response format for register_user.")
    return response


async def update_user_profile(
    authorization: Annotated[
        str,
        Field(
            min_length=1,
            description="Authorization header value (Kinde refresh token).",
        ),
    ],
    update: Annotated[
        UserProfileUpdatePayload,
        Field(description="User onboarding and/or preference updates."),
    ],
) -> Dict[str, Any]:
    """
    Call `PATCH /user/` to update onboarding and preference data.
    """
    response = await _sportscanner_api_request(
        method="PATCH",
        path="/user/",
        authorization=authorization,
        json_body=update.model_dump(mode="json", exclude_none=True),
    )
    if not isinstance(response, dict):
        raise ValueError("Unexpected response format for update_user_profile.")
    return response


async def list_notifications(
    authorization: Annotated[
        str,
        Field(
            min_length=1,
            description="Authorization header value (Kinde refresh token).",
        ),
    ],
) -> List[Dict[str, Any]]:
    """
    Call `GET /notifications/` for active notifications for the current user.
    """
    response = await _sportscanner_api_request(
        method="GET",
        path="/notifications/",
        authorization=authorization,
    )
    if not isinstance(response, list):
        raise ValueError("Unexpected response format for list_notifications.")
    return response


async def acknowledge_notification(
    notification_id: Annotated[
        str,
        Field(min_length=1, description="Notification identifier to acknowledge."),
    ],
    authorization: Annotated[
        str,
        Field(
            min_length=1,
            description="Authorization header value (Kinde refresh token).",
        ),
    ],
) -> Dict[str, Any]:
    """
    Call `POST /notifications/{notification_id}/acknowledge`.
    """
    response = await _sportscanner_api_request(
        method="POST",
        path=f"/notifications/{notification_id}/acknowledge",
        authorization=authorization,
    )
    if not isinstance(response, dict):
        raise ValueError("Unexpected response format for acknowledge_notification.")

    return {
        "notification_id": notification_id,
        "acknowledged": bool(response.get("success", False)),
        "status_code": response.get("status_code"),
    }


async def create_notification(
    authorization: Annotated[
        str,
        Field(
            min_length=1,
            description="Authorization header value (Kinde refresh token).",
        ),
    ],
    payload: Annotated[
        CreateNotificationPayload,
        Field(description="New notification values."),
    ],
) -> Dict[str, Any]:
    """
    Call `POST /notifications/admin` to create a global notification.
    """
    response = await _sportscanner_api_request(
        method="POST",
        path="/notifications/admin",
        authorization=authorization,
        json_body=payload.model_dump(mode="json"),
    )
    if not isinstance(response, dict):
        raise ValueError("Unexpected response format for create_notification.")
    return response


async def update_notification(
    notification_id: Annotated[
        str,
        Field(min_length=1, description="Notification identifier to update."),
    ],
    authorization: Annotated[
        str,
        Field(
            min_length=1,
            description="Authorization header value (Kinde refresh token).",
        ),
    ],
    payload: Annotated[
        UpdateNotificationPayload,
        Field(description="Partial notification fields to update."),
    ],
) -> Dict[str, Any]:
    """
    Call `PATCH /notifications/admin/{notification_id}`.
    """
    response = await _sportscanner_api_request(
        method="PATCH",
        path=f"/notifications/admin/{notification_id}",
        authorization=authorization,
        json_body=payload.model_dump(mode="json", exclude_none=True),
    )
    if not isinstance(response, dict):
        raise ValueError("Unexpected response format for update_notification.")
    return response
