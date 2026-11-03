"""Regression tests for the search hot path.

Covers the latency work: a repeated identical search must not touch the
database, venue metadata and the social-games exclusion must be cached, and the
response contract must stay exactly what the frontend consumes.
"""

from datetime import date, datetime, time
from typing import NamedTuple, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from sportscanner import cache
from sportscanner.api.routers.search import endpoints
from sportscanner.cache import clear_local_cache

SEARCH_DATE = date(2026, 11, 4)


class Slot(NamedTuple):
    composite_key: str
    date: date
    starting_time: time
    ending_time: time
    price: str
    spaces: int
    booking_url: Optional[str]
    last_refreshed: datetime


class VenueRow(NamedTuple):
    composite_key: str
    organisation: str
    venue_name: str
    address: str


VENUES = [
    VenueRow("court", "Better", "Court Centre", "1 Court Road"),
    VenueRow("social", "Lemon Pickleball", "Social Club", "2 Social Road"),
]
SLOTS = [
    Slot(
        "court",
        SEARCH_DATE,
        time(8),
        time(9),
        "£12.00",
        2,
        "https://example.test/book",
        datetime.now(),
    ),
    Slot(
        "court",
        SEARCH_DATE,
        time(9),
        time(10),
        "£12.00",
        0,
        "https://example.test/book",
        datetime.now(),
    ),
]


class FakeDb:
    """Stands in for the Postgres query layer and records every statement."""

    def __init__(self):
        self.calls = []

    @staticmethod
    def _render(statement):
        try:
            return str(
                statement.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
        except Exception:
            return str(statement)

    def __call__(self, engine, table, statement, params=None):
        sql = self._render(statement)
        self.calls.append(sql)
        if "sportsvenue" in sql:
            if "ORGANISATION IN" in sql.upper():
                return [VENUES[1].composite_key]
            return VENUES
        return SLOTS

    @property
    def slot_queries(self):
        return [sql for sql in self.calls if "sportsvenue" not in sql]


@pytest.fixture
def api(monkeypatch):
    fake_db = FakeDb()
    store = {}

    async def nearby(postcode, radius=10.0):
        return [
            type("V", (), {"composite_key": "court", "distance": 1.5})(),
            type("V", (), {"composite_key": "social", "distance": 2.0})(),
        ]

    def cache_get(key):
        return store.get(key)

    def cache_set(key, value, ttl_seconds=None):
        store[key] = value

    monkeypatch.setattr(endpoints.db, "get_all_rows", fake_db)
    monkeypatch.setattr(endpoints, "get_venues_near_postcode", nearby)
    # Patch both the endpoint's imports and the cache module itself, so
    # `get_or_load_json` never reaches a real Valkey instance in tests.
    monkeypatch.setattr(endpoints, "cache_get_json", cache_get)
    monkeypatch.setattr(endpoints, "cache_set_json", cache_set)
    monkeypatch.setattr(cache, "cache_get_json", cache_get)
    monkeypatch.setattr(cache, "cache_set_json", cache_set)
    clear_local_cache()

    app = FastAPI()
    app.include_router(endpoints.router, prefix="/search")
    return TestClient(app), fake_db, store


BODY = {
    "postcode": "E16 2ZG",
    "timeRange": {"starting": "06:00", "ending": "23:00"},
    "radius": 10,
    "sortBy": "distance",
    "analytics": {"consecutiveSlots": None, "specifiedVenues": None},
    "indoor": None,
}


def test_response_contract(api):
    client, _, _ = api
    response = client.post("/search/badminton?date=2026-11-04", json=BODY)
    assert response.status_code == 200

    [group] = response.json()
    assert set(group) == {
        "composite_key",
        "venue",
        "address",
        "distance",
        "price",
        "organization",
        "date",
        "availability",
        "last_refreshed",
        "healthcheck",
    }
    assert group["composite_key"] == "court"
    assert group["venue"] == "Court Centre"
    assert group["organization"] == "Better"
    assert group["distance"] == 1.5
    # Sold-out slots keep showing, flagged unavailable.
    assert [s["available"] for s in group["availability"]] == [True, False]
    assert group["healthcheck"] == "ok"


def test_social_game_venues_are_excluded(api):
    client, fake_db, _ = api
    client.post("/search/badminton?date=2026-11-04", json=BODY)
    for sql in fake_db.slot_queries:
        assert "'social'" not in sql
        assert "'court'" in sql


def test_repeat_search_is_served_without_touching_the_database(api):
    client, fake_db, store = api
    first = client.post("/search/badminton?date=2026-11-04", json=BODY)
    calls_after_first = len(fake_db.calls)
    assert calls_after_first > 0
    assert store  # response was cached

    second = client.post("/search/badminton?date=2026-11-04", json=BODY)
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(fake_db.calls) == calls_after_first  # zero extra queries


def test_venue_lookup_and_game_keys_are_cached_across_searches(api):
    client, fake_db, _ = api
    client.post("/search/badminton?date=2026-11-04", json=BODY)
    after_first = len(fake_db.calls)

    # A different date misses the response cache but must not re-read venues.
    client.post("/search/badminton?date=2026-11-05", json={**BODY, "radius": 11})
    new_calls = fake_db.calls[after_first:]
    assert len(new_calls) == 1
    assert "sportsvenue" not in new_calls[0]


def test_missing_optional_filters_use_defaults(api):
    client, _, _ = api
    response = client.post(
        "/search/badminton?date=2026-11-04",
        json={"postcode": "E16 2ZG"},
    )
    assert response.status_code == 200


def test_postcode_is_required(api):
    client, _, _ = api
    response = client.post("/search/badminton?date=2026-11-04", json={})
    assert response.status_code == 400
