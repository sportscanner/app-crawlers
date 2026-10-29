"""UK planning applications for new courts, from PlanIt.

PlanIt (planit.org.uk) aggregates the public planning registers that every UK
local planning authority must publish, and exposes them through a free,
anonymous JSON API. We search application descriptions for a sport keyword.
The default query covers London authorities, matching the London market
reports; a latitude, longitude and radius narrows the same search to a site
anywhere in the UK. Results are cached for 12 hours keyed by scope: planning
registers change daily at most, and PlanIt is a small volunteer-run service
with tight rate limits.
"""

import re
import time
from collections import Counter, defaultdict
from datetime import date
from statistics import median
from threading import Lock
from typing import Dict, List, Optional, Tuple

import httpx

from sportscanner.logger import logging

_PLANIT_URL = "https://www.planit.org.uk/api/applics/json"
_AREAS_URL = "https://www.planit.org.uk/api/areas/json"
_PAGE_SIZE = 500
# PlanIt cannot combine a keyword search with a spatial filter (the search
# index and the geometry query live in different tables), so a site search
# resolves the councils whose boundaries touch the radius and searches each
# register by name instead.
_PLANNING_AREA_TYPES = {
    "London Borough",
    "Metropolitan Borough",
    "English District",
    "English Unitary Authority",
    "Council District",
    "Scottish Council",
    "Welsh Principal Area",
    "Northern Ireland District",
}
_MAX_PAGES = 100
_CACHE_TTL_SECONDS = 12 * 60 * 60
# A partial multi-council result is retried sooner than the full 12h so a
# rate-limited register is picked up on the next visit.
_PARTIAL_CACHE_TTL_SECONDS = 30 * 60
_RETRY_STATUSES = (429, 500, 502, 503, 504)
_MAX_RETRIES = 3
_MIN_INTERVAL_SECONDS = 0.75
# PlanIt can ask for a multi-minute cool-off when rate limited. Blocking an API
# worker for that long is worse than serving the last cached copy, so only
# short waits are retried in-request.
_MAX_RETRY_PAUSE_SECONDS = 8.0
_MAX_CACHE_ENTRIES = 48
# FastAPI runs sync endpoints in a thread pool; one lock keeps concurrent
# topic/site requests from bursting PlanIt's per-IP limit.
_request_lock = Lock()
_last_request_at = 0.0
_FIELDS = (
    "uid,name,area_name,app_state,app_type,start_date,decided_date,"
    "description,link,location_x,location_y,postcode,other_fields"
)

# Registers often name private individuals as applicant or agent. Only names that
# are clearly organisations are surfaced; anything else is dropped, not shown.
_ORGANISATION_MARKERS = re.compile(
    r"\b(ltd|limited|llp|plc|cic|inc|group|associates|architects?|architecture|planning|consult\w*|design|"
    r"partnership|developments?|properties|estates?|council|club|trust|school|college|university|academy|"
    r"leisure|sports?|padel|tennis|homes|holdings|studio|surveyors?|engineers?)\b",
    re.IGNORECASE,
)


def _organisation(name: Optional[str]) -> Optional[str]:
    name = " ".join((name or "").split())
    if not name or name.lower() in {"see source", "n/a", "na", "unknown"}:
        return None
    return name if _ORGANISATION_MARKERS.search(name) else None


PLANNING_TOPICS = ("badminton", "squash", "pickleball", "padel", "tennis")

APPROVED_STATES = {"Permitted", "Conditions"}
DECIDED_STATES = APPROVED_STATES | {"Rejected"}

_NUMBER_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
}
_COURT_QUALIFIERS = r"(?:(?:new|additional|indoor|outdoor|covered|external|internal|enclosed|floodlit|single|double)\s+)*"

_cache: Dict[str, Tuple[float, dict]] = {}
_authority_cache: Dict[str, Tuple[float, List[str]]] = {}


def courts_proposed(description: str, topic: str) -> Optional[int]:
    """Sums court counts stated in an application description, e.g.
    "12no. padel courts", "seven padel courts", "2 x padel courts". Returns None
    when the description mentions the sport without a number."""
    text = (description or "").lower()
    number = r"(\d{1,2}|" + "|".join(_NUMBER_WORDS) + r")"
    pattern = re.compile(
        number
        + r"\s*(?:no\.?|nos\.?|x)?\s*"
        + _COURT_QUALIFIERS
        + re.escape(topic)
        + r"\s+courts?\b"
    )
    total = 0
    for match in pattern.finditer(text):
        token = match.group(1)
        total += int(token) if token.isdigit() else _NUMBER_WORDS[token]
    return total or None


def court_setting(description: str) -> str:
    text = (description or "").lower()
    if any(k in text for k in ("canopy", "canopies", "covered", "roof")):
        return "covered"
    if any(
        k in text
        for k in ("indoor", "internal", "within the building", "change of use")
    ):
        return "indoor"
    return (
        "outdoor"
        if any(k in text for k in ("outdoor", "external", "open air"))
        else "unknown"
    )


def _parse_date(value: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _get_page(url: str, params: dict) -> httpx.Response:
    """One PlanIt request, politely spaced and retried on 429 / 5xx.

    PlanIt is a small volunteer-run service that rate-limits by IP. A cold cache
    fanned across five sports trips it, and without a retry the whole topic
    degrades to a 503. Space requests, honour Retry-After, and back off.
    """
    global _last_request_at
    with _request_lock:
        delay = _MIN_INTERVAL_SECONDS
        response = None
        for attempt in range(_MAX_RETRIES + 1):
            gap = _MIN_INTERVAL_SECONDS - (time.time() - _last_request_at)
            if gap > 0:
                time.sleep(gap)
            response = httpx.get(
                url,
                params=params,
                headers={
                    "User-Agent": "Sportscanner market insights (sportscanner.co.uk)"
                },
                timeout=60,
            )
            _last_request_at = time.time()
            if response.status_code not in _RETRY_STATUSES or attempt == _MAX_RETRIES:
                return response
            retry_after = response.headers.get("Retry-After", "")
            if retry_after and not retry_after.isdigit():
                logging.warning(
                    f"PlanIt {response.status_code} with Retry-After {retry_after!r}; serving cached data if available"
                )
                return response
            pause = float(retry_after) if retry_after.isdigit() else delay
            if pause > _MAX_RETRY_PAUSE_SECONDS:
                logging.warning(
                    f"PlanIt {response.status_code}, cooling off for {pause:.0f}s; serving cached data if available"
                )
                return response
            logging.info(f"PlanIt {response.status_code}, retrying in {pause:.1f}s")
            time.sleep(pause)
            delay = min(delay * 2, 8.0)
        return response


def _area_search_params(topic: str, authority: str) -> dict:
    return {"search": topic, "auth": authority, "pg_sz": _PAGE_SIZE, "select": _FIELDS}


def _fetch_area(topic: str, authority: str) -> Tuple[List[dict], int]:
    """Every matching application in one planning authority's register."""
    records: List[dict] = []
    total = 0
    page = 1
    while True:
        response = _get_page(
            _PLANIT_URL, {**_area_search_params(topic, authority), "page": page}
        )
        # PlanIt answers 400 when asked for a page beyond the last one. Treat
        # that as end-of-results, not an outage: a later page must not discard
        # the pages already read, or a single bad tail request turns the whole
        # topic into a 503 (this is what happened to tennis while padel worked).
        if page > 1 and response.status_code in (400, 404, 416):
            return records, max(total, len(records))
        response.raise_for_status()
        payload = response.json()
        total = int(payload.get("total") or total)
        batch = payload.get("records") or []
        records.extend(batch)
        if len(batch) < _PAGE_SIZE or len(records) >= total:
            return records, total
        if page >= _MAX_PAGES:
            return records, total
        page += 1


def _nearby_authorities(latitude: float, longitude: float, radius: float) -> List[str]:
    """Planning authorities whose boundaries touch the site radius.

    PlanIt's area endpoint does the spatial lookup; the application endpoint
    then accepts each area name. Results are cached because boundaries do not
    move and the endpoint is rate limited too.
    """
    key = f"{latitude:.3f}:{longitude:.3f}:{radius:g}"
    cached = _authority_cache.get(key)
    if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    response = _get_page(
        _AREAS_URL,
        {
            # PlanIt takes radius in kilometres; the product works in miles.
            "lat": latitude,
            "lng": longitude,
            "krad": round(radius * 1.609344, 3),
            "select": "area_name,area_type",
            "pg_sz": 100,
        },
    )
    response.raise_for_status()
    records = response.json().get("records") or []
    authorities = sorted(
        {
            str(record["area_name"])
            for record in records
            if record.get("area_name")
            and record.get("area_type") in _PLANNING_AREA_TYPES
        }
    )
    if len(_authority_cache) >= _MAX_CACHE_ENTRIES:
        _authority_cache.pop(
            min(_authority_cache, key=lambda k: _authority_cache[k][0]), None
        )
    _authority_cache[key] = (time.time(), authorities)
    return authorities


def _fetch_records(
    topic: str, latitude=None, longitude=None, radius=None
) -> Tuple[List[dict], int, List[str], List[str]]:
    """Records plus (available, failed) authority names.

    A site radius can span several councils. If one register is rate limited
    the rest still return, and the summary flags the gap rather than silently
    reporting a partial count as complete.
    """
    if latitude is None or longitude is None:
        records, total = _fetch_area(topic, "London")
        return records, total, ["London"], []
    authorities = _nearby_authorities(latitude, longitude, radius or 3.0)
    records: List[dict] = []
    total = 0
    failed: List[str] = []
    for authority in authorities:
        try:
            area_records, area_total = _fetch_area(topic, authority)
        except Exception as exc:
            failed.append(authority)
            logging.warning(f"PlanIt fetch failed for {authority}: {exc!r}")
            continue
        records.extend(area_records)
        total += area_total
    if authorities and len(failed) == len(authorities):
        raise RuntimeError(
            f"PlanIt unavailable for all {len(failed)} authorities near {latitude:.3f},{longitude:.3f}"
        )
    return records, total, authorities, failed


def _dedupe(records: List[dict]) -> List[dict]:
    """Councils often register one scheme twice (e.g. full and associated
    listed-building applications with identical text); count it once."""
    seen = set()
    unique = []
    for r in records:
        key = (
            r.get("area_name"),
            r.get("start_date"),
            " ".join((r.get("description") or "").lower().split()),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique


def summarise(
    records: List[dict],
    topic: str,
    scope: str = "London",
    total_available: Optional[int] = None,
    authorities: Optional[List[str]] = None,
    failed_authorities: Optional[List[str]] = None,
) -> dict:
    applications = []
    for r in _dedupe(records):
        submitted = _parse_date(r.get("start_date"))
        decided = _parse_date(r.get("decided_date"))
        other = r.get("other_fields") or {}
        applications.append(
            {
                "reference": r.get("uid"),
                "borough": r.get("area_name"),
                "status": r.get("app_state") or "Unknown",
                "submitted": submitted,
                "decided": decided,
                "days_to_decision": (
                    (decided - submitted).days
                    if submitted and decided and decided >= submitted
                    else None
                ),
                "courts": courts_proposed(r.get("description"), topic),
                "setting": court_setting(r.get("description")),
                "description": r.get("description"),
                "postcode": r.get("postcode"),
                "latitude": r.get("location_y"),
                "longitude": r.get("location_x"),
                "url": r.get("link"),
                "documents_url": other.get("docs_url"),
                "decided_by": other.get("decided_by"),
                "agent": _organisation(other.get("agent_name"))
                or _organisation(other.get("agent_company")),
                "applicant": _organisation(other.get("applicant_name"))
                or _organisation(other.get("applicant_company")),
            }
        )
    applications.sort(key=lambda a: a["submitted"] or date.min, reverse=True)

    status_counts = Counter(a["status"] for a in applications)
    decided = [a for a in applications if a["status"] in DECIDED_STATES]
    approved = [a for a in decided if a["status"] in APPROVED_STATES]
    decision_days = [
        a["days_to_decision"] for a in decided if a["days_to_decision"] is not None
    ]

    by_quarter: Dict[str, Counter] = defaultdict(Counter)
    for a in applications:
        if a["submitted"]:
            quarter = f"{a['submitted'].year}-Q{(a['submitted'].month - 1) // 3 + 1}"
            by_quarter[quarter][_status_group(a["status"])] += 1

    by_borough: Dict[str, dict] = defaultdict(
        lambda: {"applications": 0, "approved": 0, "courts": 0}
    )
    for a in applications:
        row = by_borough[a["borough"] or "Unknown"]
        row["applications"] += 1
        row["approved"] += a["status"] in APPROVED_STATES
        row["courts"] += a["courts"] or 0

    pipeline_courts = sum(
        a["courts"] or 0
        for a in applications
        if _status_group(a["status"]) in ("approved", "pending")
    )

    agents: Dict[str, dict] = defaultdict(
        lambda: {"applications": 0, "approved": 0, "decided": 0, "courts": 0}
    )
    for a in applications:
        if not a["agent"]:
            continue
        row = agents[a["agent"]]
        row["applications"] += 1
        row["courts"] += a["courts"] or 0
        if a["status"] in DECIDED_STATES:
            row["decided"] += 1
            row["approved"] += a["status"] in APPROVED_STATES
    top_agents = sorted(
        (
            {
                "agent": name,
                **v,
                "approval_rate": v["approved"] / v["decided"] if v["decided"] else None,
            }
            for name, v in agents.items()
        ),
        key=lambda row: (row["applications"], row["courts"]),
        reverse=True,
    )[:10]

    by_setting = Counter()
    for a in applications:
        by_setting[a["setting"]] += a["courts"] or 0

    # Courts approved per decision year: a growth signal for new supply.
    approved_by_year: Dict[int, int] = defaultdict(int)
    for a in applications:
        if a["status"] in APPROVED_STATES and a["decided"]:
            approved_by_year[a["decided"].year] += a["courts"] or 0

    return {
        "topic": topic,
        "total_applications": len(applications),
        "approved": len(approved),
        "pending": status_counts.get("Undecided", 0),
        "rejected": status_counts.get("Rejected", 0),
        "withdrawn": status_counts.get("Withdrawn", 0),
        "approval_rate": len(approved) / len(decided) if decided else None,
        "median_days_to_decision": median(decision_days) if decision_days else None,
        "courts_proposed": sum(a["courts"] or 0 for a in applications),
        "courts_in_pipeline": pipeline_courts,
        "status_counts": dict(status_counts),
        "by_quarter": [
            {"quarter": q, **dict(c)} for q, c in sorted(by_quarter.items())
        ],
        "by_borough": sorted(
            ({"borough": b, **v} for b, v in by_borough.items()),
            key=lambda row: (row["applications"], row["courts"]),
            reverse=True,
        ),
        "top_agents": top_agents,
        "courts_by_setting": dict(by_setting),
        "approved_courts_by_year": [
            {"year": y, "courts": c} for y, c in sorted(approved_by_year.items())
        ],
        "applications": applications,
        "scope": scope,
        "total_available": (
            total_available if total_available is not None else len(applications)
        ),
        "truncated": bool(
            total_available is not None and total_available > len(records)
        ),
        "authorities": authorities or [],
        "failed_authorities": failed_authorities or [],
        "partial": bool(failed_authorities),
        "source": "PlanIt (planit.org.uk), aggregating UK local planning authority registers",
    }


def _status_group(status: str) -> str:
    if status in APPROVED_STATES:
        return "approved"
    if status == "Undecided":
        return "pending"
    if status == "Rejected":
        return "rejected"
    return "other"


def planning_summary(
    topic: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius: Optional[float] = None,
) -> Optional[dict]:
    """Cached planning summary for `topic`. Without coordinates it covers
    London; with them it covers `radius` miles around the point, anywhere in
    the UK. On a PlanIt outage, serves the last good copy if there is one."""
    if topic not in PLANNING_TOPICS:
        raise ValueError(f"Unsupported planning topic: {topic!r}")
    if (latitude is None) != (longitude is None):
        raise ValueError("latitude and longitude must be supplied together")
    if latitude is None:
        key = f"{topic}:london"
        scope = "London"
    else:
        miles = radius or 3.0
        key = f"{topic}:{latitude:.3f}:{longitude:.3f}:{miles:g}"
        scope = f"{miles:g} miles around the pin"
    cached = _cache.get(key)
    if cached:
        ttl = (
            _PARTIAL_CACHE_TTL_SECONDS
            if cached[1].get("partial")
            else _CACHE_TTL_SECONDS
        )
        if time.time() - cached[0] < ttl:
            return cached[1]
    try:
        records, total, authorities, failed = _fetch_records(
            topic, latitude, longitude, radius
        )
        summary = summarise(
            records,
            topic,
            scope=scope,
            total_available=total,
            authorities=authorities,
            failed_authorities=failed,
        )
    except Exception as exc:
        logging.warning(f"PlanIt fetch failed for {topic} ({scope}): {exc!r}")
        return cached[1] if cached else None
    summary["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if len(_cache) >= _MAX_CACHE_ENTRIES:
        _cache.pop(min(_cache, key=lambda k: _cache[k][0]), None)
    _cache[key] = (time.time(), summary)
    return summary
