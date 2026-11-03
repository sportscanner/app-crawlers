from __future__ import annotations

import asyncio
import json
import re
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from sportscanner.crawlers import local_residential
from sportscanner.crawlers.local_residential import (
    _playtomic_dates,
    _record_attempts,
    _select_playtomic_venues,
)
from sportscanner.crawlers.parsers.playtomic.core import strategy

LEGACY_SLUGS = {
    "battersea-park-millennium-arena-",
    "padel-waltham-abbey",
    "padel-people---wimbledon",
    "padel-social-club---earls-court",
    "padel-social-club---the-o2",
    "powerleague-mill-hill-",
    "powerleague-shoreditch-",
    "rocks-lane-@-dyrham-park-country-club",
    "tour-padel---avery-hill-campus-",
    "rocks-lane---barnes",
    "rocks-lane---chiswick",
    "the-london-padel-club",
}


def _venue(slug: str, latitude: float, longitude: float):
    return SimpleNamespace(
        slug=slug,
        venue_name=slug,
        latitude=latitude,
        longitude=longitude,
    )


def test_playtomic_dates_tiering():
    today = date(2026, 11, 2)
    now = 1_800_000_000.0

    dates, mid_due, long_due = _playtomic_dates({}, today, now)
    assert dates[:2] == [today, today + timedelta(days=1)]
    assert dates[-1] == today + timedelta(days=9)
    assert mid_due is True
    assert long_due is True

    state = {"playtomic": {"last_mid": now, "last_long": now}}
    dates, mid_due, long_due = _playtomic_dates(state, today, now)
    assert dates == [today, today + timedelta(days=1)]
    assert mid_due is False
    assert long_due is False

    state = {
        "playtomic": {
            "last_mid": now,
            "last_long": now - (6 * 3600 + 1),
        }
    }
    dates, mid_due, long_due = _playtomic_dates(state, today, now)
    assert mid_due is False
    assert long_due is True
    assert dates[:2] == [today, today + timedelta(days=1)]
    assert dates[-1] == today + timedelta(days=9)


def test_selection_prioritises_core_venues_and_advances_past_empty_ones():
    core_data = _venue("core-data", 51.5, -0.1)
    core_empty = _venue("core-empty", 51.5, -0.1)
    national_data = _venue("national-data", 53.5, -2.2)
    national_empty = _venue("national-empty", 53.5, -2.2)
    venues = [national_empty, core_empty, national_data, core_data]
    freshness = {"core-data": 100.0, "national-data": 100.0}

    # Fresh state: data-bearing venues sort before never-successful ones,
    # but every core venue still comes before every national venue.
    selected = _select_playtomic_venues(venues, freshness, {}, limit=2)
    assert [v.slug for v in selected] == ["core-data", "core-empty"]

    # Attempting a venue moves it to the back of its tier, so one empty venue
    # cannot be selected on every single run.
    attempts = {"core-data": 50.0}
    selected = _select_playtomic_venues(venues, freshness, attempts, limit=2)
    assert [v.slug for v in selected] == ["core-empty", "core-data"]

    # The old query selected only zero-row venues. A batch of 10 core venues
    # with data must still fit ahead of 200 national zero-row venues.
    core_venues = [_venue(f"core-{i}", 51.5, -0.1) for i in range(10)]
    national_venues = [_venue(f"national-{i}", 53.5, -2.2) for i in range(200)]
    selected = _select_playtomic_venues(
        core_venues + national_venues,
        {v.slug: 1.0 for v in core_venues},
        {},
        limit=100,
    )
    assert {v.slug for v in selected} >= {v.slug for v in core_venues}


def test_record_attempts_does_not_cool_down_on_empty_padel(monkeypatch):
    monkeypatch.setattr(local_residential, "_save_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(local_residential, "_playtomic_blocked", False)

    state = {}
    _record_attempts(
        state,
        provider_names=["playtomic"],
        counts_by_provider={"playtomic": {"padel": 0, "tennis": 1}},
        dry_run=False,
        playtomic_mid_due=True,
        playtomic_long_due=False,
    )

    entry = state["playtomic"]
    assert "blocked_until" not in entry
    assert entry["last_mid"] > 0
    assert entry["last_success_by_sport"]["tennis"] > 0
    assert "padel" not in entry["last_success_by_sport"]


def test_record_attempts_cools_down_only_when_blocked(monkeypatch):
    monkeypatch.setattr(local_residential, "_save_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(local_residential, "_playtomic_blocked", True)

    state = {}
    _record_attempts(
        state,
        provider_names=["playtomic"],
        counts_by_provider={"playtomic": {"padel": 0}},
        dry_run=False,
        playtomic_mid_due=True,
        playtomic_long_due=True,
    )

    entry = state["playtomic"]
    assert entry["blocked_until"] > 0
    assert entry["consecutive_blocked_runs"] == 1
    assert "last_mid" not in entry
    assert "last_long" not in entry


@pytest.mark.asyncio
async def test_fetch_venue_date_raises_when_every_retry_is_blocked(monkeypatch):
    async def _blocked(*args, **kwargs):
        return None

    monkeypatch.setattr(strategy, "get_with_proxy_fallback_on_403", _blocked)
    fetcher = strategy.PlaytomicAvailabilityFetcher()
    venue = SimpleNamespace(slug="test-venue", venue_name="Test Venue")

    with pytest.raises(strategy.PlaytomicBlockedError):
        await fetcher.fetch_venue_date(
            client=None,
            venue=venue,
            tenant_id="00000000-0000-0000-0000-000000000000",
            fetch_date=date(2026, 11, 2),
            semaphore=asyncio.Semaphore(1),
        )


@pytest.mark.asyncio
async def test_fetch_venue_date_empty_response_does_not_fetch_indoor_map(monkeypatch):
    class _EmptyResponse:
        def json(self):
            return []

    async def _empty(*args, **kwargs):
        return _EmptyResponse()

    async def _indoor_must_not_be_called(slug):
        raise AssertionError("indoor map should not be fetched for an empty venue")

    monkeypatch.setattr(strategy, "get_with_proxy_fallback_on_403", _empty)
    monkeypatch.setattr(
        strategy, "_fetch_resource_indoor_map", _indoor_must_not_be_called
    )
    fetcher = strategy.PlaytomicAvailabilityFetcher()
    venue = SimpleNamespace(slug="test-venue", venue_name="Test Venue")

    slots = await fetcher.fetch_venue_date(
        client=None,
        venue=venue,
        tenant_id="00000000-0000-0000-0000-000000000000",
        fetch_date=date(2026, 11, 2),
        semaphore=asyncio.Semaphore(1),
    )
    assert slots == []


def test_fetcher_accepts_pacing_and_timeout_settings():
    fetcher = strategy.PlaytomicAvailabilityFetcher(
        min_request_interval=2.0,
        tls_attempts=1,
        request_timeout=10.0,
    )
    assert fetcher.min_request_interval == 2.0
    assert fetcher.tls_attempts == 1
    assert fetcher.request_timeout == 10.0


def test_playtomic_venues_json_has_no_duplicate_names_or_legacy_slugs():
    venues_path = Path(__file__).resolve().parents[2] / "sportscanner" / "venues.json"
    data = json.loads(venues_path.read_text())
    block = next(
        item
        for item in data
        if item.get("organisation_website") == "https://playtomic.com"
    )
    slugs = [venue["slug"] for venue in block["venues"]]
    names = [venue["venue_name"] for venue in block["venues"]]

    assert len(slugs) == len(set(slugs))
    assert len(names) == len(set(names))
    normalized_names = [
        re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", name.lower())).strip()
        for name in names
    ]
    assert len(normalized_names) == len(set(normalized_names))
    assert not LEGACY_SLUGS.intersection(slugs)
    assert not LEGACY_SLUGS.intersection(strategy.SLUG_TO_TENANT_ID)
    assert {
        "s3-finchley-rd",
        "the-padel-hub-kt19-epsom",
        "essendon-country-club-uk",
    }.issubset(slugs)
    assert {
        "s3-finchley-rd",
        "the-padel-hub-kt19-epsom",
        "essendon-country-club-uk",
    }.issubset(strategy.SLUG_TO_TENANT_ID)
