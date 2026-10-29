"""Refresh the bundled UK planning snapshots from PlanIt.

Run from app-crawlers:

    python -m sportscanner.insights.refresh_planning

PlanIt is a small volunteer-run service with tight per-IP limits, and its
production egress can be blocked entirely. The API therefore reads these
snapshots instead of calling PlanIt on every request. Each sport is fetched
nationwide once, trimmed to the fields the map and panel use, and written as
a gzipped JSON file under `insights/data/planning/`.

Refresh cadence: planning registers change daily at most, so monthly or
weekly is plenty. Re-run this from a network PlanIt accepts, then commit the
updated `.json.gz` files.
"""

import gzip
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from sportscanner.insights.planning import (
    _FIELDS,
    _MAX_PAGES,
    _PAGE_SIZE,
    _PLANIT_URL,
    _get_page,
    summarise,
    PLANNING_TOPICS,
)

_TARGET = Path(__file__).resolve().parent / "data" / "planning"
_DESCRIPTION_LIMIT = 800


def _get_page_with_wait(params: dict):
    """CLI refreshes may wait out PlanIt's multi-minute cool-offs.

    The API path deliberately gives up after a short wait, but a maintenance
    job can afford to be patient so a full nationwide snapshot completes.
    """
    while True:
        response = _get_page(_PLANIT_URL, params)
        if response.status_code != 429:
            return response
        retry_after = response.headers.get("Retry-After", "")
        wait = int(retry_after) if retry_after.isdigit() else 60
        print(f"PlanIt 429; waiting {wait + 5}s before retrying", flush=True)
        time.sleep(min(wait + 5, 900))


def _fetch_nationwide(topic: str):
    """Every record matching `topic`, without an authority filter."""
    records = []
    total = 0
    page = 1
    while True:
        response = _get_page_with_wait(
            {
                "search": topic,
                "pg_sz": _PAGE_SIZE,
                "page": page,
                "select": _FIELDS,
            },
        )
        if page > 1 and response.status_code in (400, 404, 416):
            return records, max(total, len(records))
        response.raise_for_status()
        payload = response.json()
        total = int(payload.get("total") or total)
        batch = payload.get("records") or []
        records.extend(batch)
        if len(batch) < _PAGE_SIZE or len(records) >= total or page >= _MAX_PAGES:
            return records, total
        page += 1


def _iso(value):
    return value.isoformat() if isinstance(value, date) else value


def main(topics=None):
    _TARGET.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for topic in topics or PLANNING_TOPICS:
        records, total = _fetch_nationwide(topic)
        summary = summarise(records, topic)
        applications = []
        for application in summary["applications"]:
            latitude = application.get("latitude")
            longitude = application.get("longitude")
            if latitude is None or longitude is None:
                continue
            latitude, longitude = float(latitude), float(longitude)
            if not (49 <= latitude <= 61 and -8 <= longitude <= 2):
                continue
            applications.append(
                {
                    **application,
                    "submitted": _iso(application.get("submitted")),
                    "decided": _iso(application.get("decided")),
                    "description": (application.get("description") or "")[
                        :_DESCRIPTION_LIMIT
                    ],
                }
            )
        payload = {
            "topic": topic,
            "generated_at": generated_at,
            "source": "PlanIt (planit.org.uk), UK local planning authority registers",
            "total": total,
            "applications": applications,
        }
        path = _TARGET / f"{topic}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        print(
            f"{topic}: {len(applications)} applications "
            f"({total} records), {path.stat().st_size / 1_000_000:.2f} MB"
        )


if __name__ == "__main__":
    requested = sys.argv[1:]
    unknown = [topic for topic in requested if topic not in PLANNING_TOPICS]
    if unknown:
        raise SystemExit(f"Unknown topic(s): {', '.join(unknown)}")
    main(requested or None)
