"""Regression tests for insights report caching and the venue list cache.

The insights reports cost 0.5 to 4 seconds of aggregation each, and
`/insights/` builds all five. Serving an expired body while a background thread
rebuilds it is what keeps that off the request path, so it is tested directly.
"""

import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sportscanner import cache
from sportscanner.api.routers.venues import endpoints as venues_endpoints
from sportscanner.cache import clear_local_cache
from sportscanner.insights import service


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """No real Valkey, no process-local leftovers, no background threads leaking."""
    store = {}

    monkeypatch.setattr(cache, "cache_get_json", lambda key: store.get(key))
    monkeypatch.setattr(
        cache,
        "cache_set_json",
        lambda key, value, ttl_seconds=None: store.__setitem__(key, value),
    )
    clear_local_cache()
    service._cache.clear()
    service._cache_in_flight.clear()
    yield store
    service._cache.clear()
    service._cache_in_flight.clear()


def _age(key, seconds):
    created, value = service._cache[key]
    service._cache[key] = (created - seconds, value)


def test_fresh_entry_is_returned_without_building():
    calls = []

    def build():
        calls.append(1)
        return {"value": 1}

    first = service._cached("k", build)
    second = service._cached("k", build)
    assert first == second == {"value": 1}
    assert len(calls) == 1


def test_expired_entry_is_served_immediately_and_refreshed_in_background():
    built = threading.Event()
    release = threading.Event()

    def slow_build():
        release.wait(timeout=5)
        built.set()
        return {"value": 2}

    service._cached("k", lambda: {"value": 1})
    _age("k", service._CACHE_TTL_SECONDS + 1)

    started = time.perf_counter()
    value = service._cached("k", slow_build)
    elapsed = time.perf_counter() - started

    # The stale body comes back at once, not after the rebuild.
    assert value == {"value": 1}
    assert elapsed < 0.5
    assert "k" in service._cache_in_flight

    release.set()
    assert built.wait(timeout=5)
    for _ in range(50):
        if "k" not in service._cache_in_flight:
            break
        time.sleep(0.02)
    assert service._cache["k"][1] == {"value": 2}


def test_entry_beyond_stale_window_is_rebuilt_synchronously():
    service._cached("k", lambda: {"value": 1})
    _age("k", service._CACHE_STALE_SECONDS + 1)

    value = service._cached("k", lambda: {"value": 3})
    assert value == {"value": 3}


def test_only_one_refresh_per_key_runs_at_a_time():
    release = threading.Event()
    builds = []

    def build():
        builds.append(1)
        release.wait(timeout=5)
        return {"value": 9}

    service._cached("k", lambda: {"value": 1})
    _age("k", service._CACHE_TTL_SECONDS + 1)

    for _ in range(5):
        service._cached("k", build)
    release.set()

    for _ in range(50):
        if "k" not in service._cache_in_flight:
            break
        time.sleep(0.02)
    assert len(builds) == 1


def test_failed_background_refresh_keeps_serving_the_previous_body():
    def failing():
        raise RuntimeError("boom")

    service._cached("k", lambda: {"value": 1})
    _age("k", service._CACHE_TTL_SECONDS + 1)
    assert service._cached("k", failing) == {"value": 1}

    for _ in range(50):
        if "k" not in service._cache_in_flight:
            break
        time.sleep(0.02)
    assert service._cache["k"][1] == {"value": 1}


class FakeVenueList:
    def __init__(self):
        self.calls = 0

    def __call__(self, sports=None, limit=None):
        self.calls += 1
        return [
            SimpleNamespace(
                composite_key="abc12345",
                venue_name="Test Centre",
                address="1 Test Street",
                sports=["badminton", "padel"],
                latitude=51.5,
                longitude=-0.1,
            )
        ]


@pytest.fixture
def venues_client(monkeypatch):
    fake = FakeVenueList()
    monkeypatch.setattr(venues_endpoints, "get_venues_from_database", fake)
    app = FastAPI()
    app.include_router(venues_endpoints.router, prefix="/venues")
    return TestClient(app), fake


def test_venue_list_is_cached_and_shape_is_stable(venues_client):
    client, fake = venues_client

    first = client.get("/venues/")
    assert first.status_code == 200
    assert first.json() == [
        {
            "composite_key": "abc12345",
            "venue_name": "Test Centre",
            "address": "1 Test Street",
            "sports": ["badminton", "padel"],
            "latitude": 51.5,
            "longitude": -0.1,
        }
    ]
    assert "max-age" in first.headers["cache-control"]

    second = client.get("/venues/")
    assert second.json() == first.json()
    assert fake.calls == 1  # second request never touched the database


def test_venue_list_limit_slices_the_cached_list(venues_client):
    client, _ = venues_client
    assert len(client.get("/venues/?limit=1").json()) == 1
    assert len(client.get("/venues/").json()) == 1


def test_venues_by_sport_is_cached_per_sport(venues_client):
    client, fake = venues_client
    first = client.get("/venues/sports/padel")
    assert first.status_code == 200
    client.get("/venues/sports/padel")
    assert fake.calls == 1

    client.get("/venues/sports/squash")
    assert fake.calls == 2
