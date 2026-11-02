"""Crawl the providers that GitHub Actions cannot keep fresh.

Everyone Active, UEL SportsDock, LTA ClubSpark and Mytime Active fail 100% from
GitHub Actions runner IPs and answer normally from a residential one (see
docs/clubs/everyone-active.md, uel-sportsdock.md, clubspark.md and
mytime-active.md). The paid rotating proxy was removed in August 2026 because
its exits were blocklisted by the same WAFs as the runner range, so the laptop
connection is the egress now.

Playtomic, Matchi and Gladstone Go are also here: the 2026-10-28 freshness
audit found zero of their tracked venues refreshed in the previous 35 minutes,
while a local dry run returned 14,238 Playtomic padel slots, 2,179 Matchi padel
slots and 847 Gladstone padel slots in 13 seconds. Their WAFs are the same
CloudFront/Cloudflare class, so Actions is the common factor, not the code.
Playtomic throttles repeated passes, so its padel worker refreshes a paced
rotation: London venues first, then national venues, with per-venue attempt
timestamps so a venue that returns no slots cannot starve the rest. Today and
tomorrow are fetched for every selected venue; the mid-week and far date tiers
are refreshed for the first few venues in each batch when those tiers are due.

This is deliberately separate from `sportscanner/crawlers/pipeline.py`: the
main 15-minute pipeline still runs every provider from Actions, including the
ones that always fail there. This script only refreshes the venues those
providers own, so running it locally does not duplicate the whole crawl.

The upserts go through the same `insert_records_to_table()`, so they are
idempotent and can run alongside the Actions pipeline. Stale-marking is scoped
to the composite keys and dates present in each provider's payload, so other
providers' rows are never touched.

Run manually:

    python -m sportscanner.crawlers.local_residential
    python -m sportscanner.crawlers.local_residential --only clubspark
    python -m sportscanner.crawlers.local_residential --dry-run

Scheduled runs (no `--only`) run Everyone Active, UEL, Matchi, Gladstone Go,
ClubSpark and Mytime Active, with ClubSpark and Mytime Active held to an hourly
cadence. Playtomic and Places Leisure are excluded from the default set and run
from their own launchd agents and locks, because one pass of either is far
longer than a tick: Playtomic covers 457 venues, and Places Leisure needs one
paced request per scheduled timeslot (~45 minutes for three days across both
sports). The cadence lives in
`~/Library/Logs/sportscanner/residential-crawl-state.json`, which also records
the slot count of each provider's last run. Passing `--only` runs that selection
regardless of cadence.

Installed as three launchd agents: `uk.co.sportscanner.residential-crawl` for the
mixed providers every 15 minutes, `uk.co.sportscanner.residential-crawl-playtomic`
every 30 minutes and `uk.co.sportscanner.residential-crawl-placesleisure` every
two hours.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Must be set before any sportscanner import: variables.py picks .env (prod) vs
# .dev.env from ENV at import time.
os.environ.setdefault("ENV", "prod")
# The laptop is the only egress for these providers, so do not burst them the
# way a throwaway runner can: 8 concurrent requests per provider instead of 20.
os.environ.setdefault("CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER", "8")
# Playtomic padel is disabled in the shared pipeline because the national venue
# list makes it slow enough to stall that sport job. This worker is the only
# place it works (residential egress) and runs it hourly, so enable it here.
os.environ.setdefault("PLAYTOMIC_PADEL_ENABLED", "true")
# Pace the club-page metadata requests too. The disk cache means this only
# matters on the first run for a venue, but a cold run would otherwise fire one
# extra request per venue alongside the availability calls.
os.environ.setdefault("PLAYTOMIC_INDOOR_REQUEST_INTERVAL_SECONDS", "2.0")

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from sportscanner.logger import logging
from sportscanner.crawlers.anonymize.proxies import httpxAsyncClient
from sportscanner.crawlers.helpers import SportscannerCrawlerBot
from sportscanner.crawlers.parsers.clubspark.padel.scraper import (
    coroutines as ClubSparkPadelScraperCoroutines,
)
from sportscanner.crawlers.parsers.clubspark.tennis.scraper import (
    coroutines as ClubSparkTennisScraperCoroutines,
)
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.everyoneactive.badminton.scraper import (
    coroutines as EveryoneActiveBadmintonScraperCoroutines,
)
from sportscanner.crawlers.parsers.everyoneactive.squash.scraper import (
    coroutines as EveryoneActiveSquashScraperCoroutines,
)
from sportscanner.crawlers.parsers.gladstonego.padel.scraper import (
    coroutines as GladstoneGoPadelScraperCoroutines,
)
from sportscanner.crawlers.parsers.matchi.padel.scraper import (
    coroutines as MatchiPadelScraperCoroutines,
)
from sportscanner.crawlers.parsers.matchi.tennis.scraper import (
    coroutines as MatchiTennisScraperCoroutines,
)
from sportscanner.crawlers.parsers.mytimeactive.badminton.scraper import (
    coroutines as MytimeActiveBadmintonScraperCoroutines,
)
from sportscanner.crawlers.parsers.mytimeactive.squash.scraper import (
    coroutines as MytimeActiveSquashScraperCoroutines,
)
from sportscanner.crawlers.parsers.playtomic.padel.scraper import (
    PlaytomicPadelCrawler,
    coroutines as PlaytomicPadelScraperCoroutines,
)
from sportscanner.crawlers.parsers.playtomic.core.strategy import SLUG_TO_TENANT_ID
from sportscanner.crawlers.parsers.playtomic.pickleball.scraper import (
    coroutines as PlaytomicPickleballScraperCoroutines,
)
from sportscanner.crawlers.parsers.playtomic.tennis.scraper import (
    coroutines as PlaytomicTennisScraperCoroutines,
)
from sportscanner.crawlers.parsers.placesleisure.badminton.scraper import (
    coroutines as PlacesLeisureBadmintonScraperCoroutines,
)
from sportscanner.crawlers.parsers.placesleisure.pickleball.scraper import (
    coroutines as PlacesLeisurePickleballScraperCoroutines,
)
from sportscanner.crawlers.parsers.uelsportsdock.badminton.scraper import (
    coroutines as UELSportsDockBadmintonScraperCoroutines,
)
from sportscanner.crawlers.pipeline import (
    fill_estimated_prices,
    flatten_responses,
    record_slot_history,
)

from sportscanner.storage.postgres.database import (
    delete_past_slots,
    engine,
    insert_records_to_table,
)
from sportscanner.storage.postgres.tables import (
    BadmintonMasterTable,
    PadelMasterTable,
    PickleballMasterTable,
    SquashMasterTable,
    TennisMasterTable,
)
from sportscanner.variables import settings

# Same horizons the main pipeline uses per sport. The full set of providers
# below runs in around 30 seconds and writes about 27k slots, so it fits a
# 15-minute tick with plenty of headroom.
HORIZON_DAYS = {
    "badminton": 10,
    "squash": 15,
    "pickleball": 15,
    "padel": 10,
    "tennis": 10,
}

MASTER_TABLES = {
    "badminton": BadmintonMasterTable,
    "squash": SquashMasterTable,
    "pickleball": PickleballMasterTable,
    "padel": PadelMasterTable,
    "tennis": TennisMasterTable,
}

# Providers whose crawl is too long for the shared tick, with their own date
# horizon per sport. Places Leisure issues one paced request per scheduled
# timeslot (~3s apart), so ten days would run for hours; the GitHub job uses
# the same three-day window.
PROVIDER_HORIZON_DAYS = {
    "placesleisure": {"badminton": 3, "pickleball": 3},
}

PROVIDER_SCRAPERS = {
    "everyoneactive": {
        "label": "Everyone Active",
        "scrapers": {
            "badminton": EveryoneActiveBadmintonScraperCoroutines,
            "squash": EveryoneActiveSquashScraperCoroutines,
        },
    },
    "uelsportsdock": {
        "label": "UEL SportsDock",
        "scrapers": {
            "badminton": UELSportsDockBadmintonScraperCoroutines,
        },
    },
    "playtomic": {
        "label": "Playtomic",
        "scrapers": {
            "padel": PlaytomicPadelScraperCoroutines,
            "pickleball": PlaytomicPickleballScraperCoroutines,
            "tennis": PlaytomicTennisScraperCoroutines,
        },
    },
    "matchi": {
        "label": "Matchi",
        "scrapers": {
            "padel": MatchiPadelScraperCoroutines,
            "tennis": MatchiTennisScraperCoroutines,
        },
    },
    "gladstonego": {
        "label": "Gladstone Go",
        "scrapers": {
            "padel": GladstoneGoPadelScraperCoroutines,
        },
    },
    "clubspark": {
        "label": "LTA ClubSpark",
        "scrapers": {
            "tennis": ClubSparkTennisScraperCoroutines,
            "padel": ClubSparkPadelScraperCoroutines,
        },
    },
    "mytimeactive": {
        "label": "Mytime Active",
        "scrapers": {
            "badminton": MytimeActiveBadmintonScraperCoroutines,
            "squash": MytimeActiveSquashScraperCoroutines,
        },
    },
    "placesleisure": {
        "label": "Places Leisure",
        "scrapers": {
            "badminton": PlacesLeisureBadmintonScraperCoroutines,
            "pickleball": PlacesLeisurePickleballScraperCoroutines,
        },
    },
}

LOG_DIR = Path.home() / "Library" / "Logs" / "sportscanner"
STATE_PATH = LOG_DIR / "residential-crawl-state.json"
STATE_LOCK_PATH = LOG_DIR / "residential-crawl-state.lock"

# Playtomic now covers 461 venues and one pass takes about 23 minutes, longer
# than the 15-minute tick. It runs from its own launchd agent and lock so it
# cannot starve the providers that need to be fresh every 15 minutes.
DEDICATED_PROVIDERS = {"playtomic", "placesleisure"}

# Everyone Active, UEL, Matchi and Gladstone Go run on every tick. Playtomic,
# ClubSpark and Mytime Active rate-limit back-to-back probing per source IP:
# Playtomic returned 14,238 padel slots on a cold IP, then 1,106 and 953 on the
# next two 15-minute passes; ClubSpark dropped from ~4,500 slots to ~500 on a
# second pass a minute later. Those three run hourly.
MIN_INTERVAL_SECONDS = {
    "everyoneactive": 0,
    "uelsportsdock": 0,
    "matchi": 0,
    "gladstonego": 0,
    "playtomic": 0,  # dedicated agent; date tiering handles the rate limit
    "clubspark": 3600,
    "mytimeactive": 3600,
    "placesleisure": 2 * 3600,
}
# launchd ticks drift by a few seconds; without slack an hourly provider would
# see 3595s elapsed, skip, and wait another 15 minutes.
_TICK_SLACK_SECONDS = 120


def _load_state() -> Dict[str, dict]:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(
    state: Dict[str, dict], provider_names: Optional[Sequence[str]] = None
) -> None:
    """Merge this run's provider entries into the latest file.

    The 15-minute agent and the Playtomic agent run in separate processes and
    share this file. Writing the whole in-memory copy would clobber the other
    process's timestamps, so re-read under a lock and only replace the keys this
    run actually touched.
    """
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_LOCK_PATH, "w") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        latest = _load_state()
        if provider_names is None:
            latest = dict(state)
        else:
            for name in provider_names:
                if name in state:
                    latest[name] = state[name]
        tmp_path = STATE_PATH.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(latest, indent=2, sort_keys=True))
        os.replace(tmp_path, STATE_PATH)
        fcntl.flock(lock_handle, fcntl.LOCK_UN)


def _due_providers(
    state: Dict[str, dict], now_ts: float, names: Sequence[str]
) -> List[str]:
    due = []
    for name in names:
        interval = MIN_INTERVAL_SECONDS[name]
        last_attempt = state.get(name, {}).get("last_attempt", 0)
        if interval <= 0 or now_ts - last_attempt >= interval - _TICK_SLACK_SECONDS:
            due.append(name)
    return due


PLAYTOMIC_MID_INTERVAL_SECONDS = 3600
PLAYTOMIC_LONG_INTERVAL_SECONDS = 6 * 3600


def _playtomic_dates(
    state: Dict[str, dict], today: date, now_ts: float
) -> Tuple[List[date], bool, bool]:
    """Tier Playtomic padel dates: today and tomorrow every run, mid-week dates
    hourly, far dates every six hours. The extended dates are only applied to
    the first PLAYTOMIC_EXTENDED_VENUES in each batch, so the request count
    stays bounded while every venue eventually gets its future dates."""
    entry = state.get("playtomic", {})
    dates = [today, today + timedelta(days=1)]
    mid_due = (
        now_ts - entry.get("last_mid", 0)
        >= PLAYTOMIC_MID_INTERVAL_SECONDS - _TICK_SLACK_SECONDS
    )
    long_due = (
        now_ts - entry.get("last_long", 0)
        >= PLAYTOMIC_LONG_INTERVAL_SECONDS - _TICK_SLACK_SECONDS
    )
    if mid_due:
        dates.extend(today + timedelta(days=i) for i in range(2, 7))
    if long_due:
        dates.extend(today + timedelta(days=i) for i in range(7, 10))
    return dates, mid_due, long_due


def _acquire_lock(scope: str) -> Optional[object]:
    """One run per scope: Playtomic must not block the 15-minute providers."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handle = open(LOG_DIR / f"residential-crawl-{scope}.lock", "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _selected_providers(only: Optional[str]) -> List[str]:
    if not only:
        return [name for name in PROVIDER_SCRAPERS if name not in DEDICATED_PROVIDERS]
    requested = [name.strip().lower() for name in only.split(",") if name.strip()]
    unknown = [name for name in requested if name not in PROVIDER_SCRAPERS]
    if unknown:
        raise SystemExit(
            f"Unknown provider(s): {', '.join(unknown)}. "
            f"Choose from: {', '.join(PROVIDER_SCRAPERS)}"
        )
    return requested


PLAYTOMIC_PACED_VENUES = int(os.environ.get("PLAYTOMIC_PACED_VENUES", "100"))
PLAYTOMIC_EXTENDED_VENUES = int(os.environ.get("PLAYTOMIC_EXTENDED_VENUES", "10"))
PLAYTOMIC_MIN_REQUEST_INTERVAL_SECONDS = float(
    os.environ.get("PLAYTOMIC_MIN_REQUEST_INTERVAL_SECONDS", "2.0")
)
PLAYTOMIC_TLS_ATTEMPTS = int(os.environ.get("PLAYTOMIC_TLS_ATTEMPTS", "1"))
PLAYTOMIC_REQUEST_TIMEOUT_SECONDS = float(
    os.environ.get("PLAYTOMIC_REQUEST_TIMEOUT_SECONDS", "10")
)
PLAYTOMIC_VENUE_TIMEOUT_SECONDS = float(
    os.environ.get("PLAYTOMIC_VENUE_TIMEOUT_SECONDS", "120")
)
PLAYTOMIC_MAX_CONSECUTIVE_BLOCKED = int(
    os.environ.get("PLAYTOMIC_MAX_CONSECUTIVE_BLOCKED", "5")
)
PLAYTOMIC_BLOCK_COOLDOWN_SECONDS = int(
    os.environ.get("PLAYTOMIC_BLOCK_COOLDOWN_SECONDS", "1800")
)

# Consumer coverage is London. The national Playtomic list is much larger and
# mostly returns no padel availability, so it used to take every rotation slot.
# Core venues go first; national venues fill the remaining slots and rotate on
# a slower cycle. Bounds are deliberately a little wider than Greater London.
PLAYTOMIC_CORE_BOUNDS = (51.20, 51.80, -0.70, 0.40)

# Set by the paced crawler when Playtomic starts 403ing every venue; used to
# put the provider into a cooldown instead of hammering it every 30 minutes.
_playtomic_blocked = False


def _is_core_venue(venue) -> bool:
    if venue.latitude is None or venue.longitude is None:
        return False
    min_lat, max_lat, min_lon, max_lon = PLAYTOMIC_CORE_BOUNDS
    return (
        min_lat <= venue.latitude <= max_lat and min_lon <= venue.longitude <= max_lon
    )


def _playtomic_freshness() -> Dict[str, float]:
    """Newest padel write per Playtomic slug, used to order the rotation."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
                select v.slug, max(p.last_refreshed)
                from sportsvenue v
                left join padel p on p.composite_key = v.composite_key
                where v.organisation_website = 'https://playtomic.com'
                  and 'padel' = any(v.sports)
                group by v.slug
                """)).fetchall()
    return {
        slug: refreshed_at.timestamp()
        for slug, refreshed_at in rows
        if refreshed_at is not None
    }


def _select_playtomic_venues(
    venues: Sequence,
    freshness: Dict[str, float],
    attempts: Dict[str, float],
    limit: int,
) -> List:
    """Core London first, then least-recently-attempted, then stalest data.

    `venue_attempts` is the important part: the old query ordered by
    `max(last_refreshed) nulls first`, so the 131 venues that had never
    returned a slot were selected on every run. This ordering advances past a
    venue even when it returns an empty 200, so one unproductive batch cannot
    starve the rest of the estate.
    """

    def sort_key(venue):
        core_rank = 0 if _is_core_venue(venue) else 1
        last_attempt = float(attempts.get(venue.slug, 0.0))
        has_data_rank = 0 if venue.slug in freshness else 1
        return (
            core_rank,
            last_attempt,
            has_data_rank,
            freshness.get(venue.slug, 0.0),
        )

    return sorted(venues, key=sort_key)[:limit]


async def _playtomic_padel_coroutine(
    dates: Sequence[date],
    state: Dict[str, dict],
) -> List[UnifiedParserSchema]:
    """Refresh Playtomic padel venues in a paced, fair rotation.

    Each run takes up to PLAYTOMIC_PACED_VENUES venues, London venues first.
    The first PLAYTOMIC_EXTENDED_VENUES also fetch the mid/far date tiers when
    those are due; the rest fetch today and tomorrow only. Per-venue attempt
    timestamps in the state file make the rotation advance even when a venue
    returns no slots, and an actual 403/429 block stops the run instead of an
    empty 200.
    """
    global _playtomic_blocked
    _playtomic_blocked = False

    entry = state.setdefault("playtomic", {})
    attempts: Dict[str, float] = entry.setdefault("venue_attempts", {})

    crawler = PlaytomicPadelCrawler(
        min_request_interval=PLAYTOMIC_MIN_REQUEST_INTERVAL_SECONDS,
        tls_attempts=PLAYTOMIC_TLS_ATTEMPTS,
        request_timeout=PLAYTOMIC_REQUEST_TIMEOUT_SECONDS,
    )
    venues = crawler.get_venues_by_sport_offering(sport="padel")
    current_slugs = {venue.slug for venue in venues}
    for slug in list(attempts):
        if slug not in current_slugs:
            del attempts[slug]

    freshness = _playtomic_freshness()
    selected = _select_playtomic_venues(
        venues, freshness, attempts, PLAYTOMIC_PACED_VENUES
    )
    base_dates = list(dates[:2])
    extended_dates = list(dates)

    slots: List[UnifiedParserSchema] = []
    attempted = 0
    blocked_venues = 0
    empty_venues = 0
    consecutive_blocked = 0
    semaphore = asyncio.Semaphore(settings.CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER)

    async with httpxAsyncClient() as client:
        for index, venue in enumerate(selected):
            tenant_id = SLUG_TO_TENANT_ID.get(venue.slug)
            if not tenant_id:
                logging.warning(f"Playtomic: no tenant_id for {venue.slug}, skipping")
                continue
            venue_dates = (
                extended_dates if index < PLAYTOMIC_EXTENDED_VENUES else base_dates
            )
            try:
                venue_slots, blocked = await asyncio.wait_for(
                    crawler.crawl_venue_dates(
                        client, venue, tenant_id, venue_dates, semaphore
                    ),
                    timeout=PLAYTOMIC_VENUE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logging.warning(
                    f"Playtomic: {venue.venue_name} timed out after "
                    f"{PLAYTOMIC_VENUE_TIMEOUT_SECONDS:.0f}s; moving on"
                )
                venue_slots, blocked = [], False
            attempts[venue.slug] = time.time()
            attempted += 1
            slots.extend(venue_slots)

            if blocked:
                blocked_venues += 1
                if not venue_slots:
                    consecutive_blocked += 1
                else:
                    consecutive_blocked = 0
            else:
                consecutive_blocked = 0

            if not venue_slots and not blocked:
                empty_venues += 1

            if consecutive_blocked >= PLAYTOMIC_MAX_CONSECUTIVE_BLOCKED:
                _playtomic_blocked = True
                logging.warning(
                    "Playtomic paced refresh: "
                    f"{consecutive_blocked} venues in a row were blocked; "
                    "stopping this run"
                )
                break

    logging.info(
        f"Playtomic paced refresh: selected {len(selected)}, "
        f"attempted {attempted}, {len(slots)} slot(s), "
        f"{blocked_venues} blocked venue(s), {empty_venues} empty venue(s), "
        f"date tiers={len(extended_dates)}"
    )
    return slots


async def _crawl(
    provider_names: Sequence[str],
    dates_by_sport: Dict[str, List[date]],
    playtomic_dates: Sequence[date],
    state: Dict[str, dict],
) -> List[Tuple[str, str, str, List[UnifiedParserSchema]]]:
    tasks = []
    for name in provider_names:
        spec = PROVIDER_SCRAPERS[name]
        for sport, factory in spec["scrapers"].items():
            if (
                name == "playtomic"
                and sport == "padel"
                and not settings.PLAYTOMIC_PADEL_ENABLED
            ):
                continue
            # Playtomic padel is throttled on a full sweep, so refresh a paced,
            # fair rotation of venues. Tennis and pickleball are small enough
            # to keep the full horizon.
            if name == "playtomic" and sport == "padel":
                task = _playtomic_padel_coroutine(playtomic_dates, state)
            else:
                horizon = PROVIDER_HORIZON_DAYS.get(name, {}).get(sport)
                task = factory(
                    dates_by_sport[sport][:horizon]
                    if horizon
                    else dates_by_sport[sport]
                )
            tasks.append((name, spec["label"], sport, task))

    results = await SportscannerCrawlerBot(*[task[3] for task in tasks])

    labelled: List[Tuple[str, str, str, List[UnifiedParserSchema]]] = []
    for (name, label, sport, _coroutine), result in zip(tasks, results):
        labelled.append((name, label, sport, result or []))
    return labelled


def _db_write(operation, *args, attempts: int = 3, **kwargs):
    """Retry an idempotent write when Aiven drops the SSL connection mid-batch."""
    for attempt in range(1, attempts + 1):
        try:
            return operation(*args, **kwargs)
        except OperationalError as exc:
            if attempt == attempts:
                raise
            logging.warning(
                f"DB write failed ({exc.__class__.__name__}), reconnecting and "
                f"retrying ({attempt}/{attempts})"
            )
            engine.dispose()
            time.sleep(2 * attempt)


def _write_sport(
    sport: str,
    slots: List[UnifiedParserSchema],
    run_started: datetime,
    dry_run: bool,
) -> int:
    table = MASTER_TABLES[sport]
    if not slots:
        logging.warning(f"{sport}: no slots returned, table left untouched")
        return 0

    if dry_run:
        logging.info(f"{sport}: {len(slots)} slot(s) ready (dry run, not written)")
        return len(slots)

    _db_write(delete_past_slots, table)
    _db_write(insert_records_to_table, slots, table)
    record_slot_history(table, run_started=run_started)
    logging.success(
        f"{sport}: {len(slots)} slot(s) upserted into {table.__tablename__}"
    )
    return len(slots)


def _record_attempts(
    state: Dict[str, dict],
    provider_names: Sequence[str],
    counts_by_provider: Dict[str, Dict[str, int]],
    dry_run: bool,
    playtomic_mid_due: bool = False,
    playtomic_long_due: bool = False,
) -> None:
    """Persist cadence state, so a 403 storm is not retried on the next tick."""
    if dry_run:
        return

    now_ts = time.time()
    for name in provider_names:
        counts = counts_by_provider.get(name, {})
        entry = state.setdefault(name, {})
        entry["last_attempt"] = now_ts
        entry["last_counts"] = counts
        if any(counts.values()):
            entry["last_success"] = now_ts
        successes_by_sport = entry.setdefault("last_success_by_sport", {})
        for sport, count in counts.items():
            if count:
                successes_by_sport[sport] = now_ts
        if name == "playtomic":
            # Only a real 403/429 storm sets the cooldown. A zero padel count
            # can simply mean every selected venue had no availability, and
            # pausing the provider for two hours in that case was what left
            # hundreds of venues days old.
            if _playtomic_blocked:
                entry["blocked_until"] = now_ts + PLAYTOMIC_BLOCK_COOLDOWN_SECONDS
                entry["consecutive_blocked_runs"] = (
                    entry.get("consecutive_blocked_runs", 0) + 1
                )
            else:
                entry.pop("blocked_until", None)
                entry["consecutive_blocked_runs"] = 0
                # The extended tier was attempted by the first venues in the
                # batch, even if none of them had slots. Mark it done so the
                # next run does not fetch the same tier again.
                if playtomic_mid_due and PLAYTOMIC_EXTENDED_VENUES > 0:
                    entry["last_mid"] = now_ts
                if playtomic_long_due and PLAYTOMIC_EXTENDED_VENUES > 0:
                    entry["last_long"] = now_ts

    try:
        _save_state(state, provider_names)
    except OSError as exc:
        logging.warning(f"Could not write crawl state: {exc!r}")


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Residential-IP crawl for providers blocked from GitHub Actions"
    )
    parser.add_argument(
        "--only",
        help=(
            "Comma-separated subset: everyoneactive, uelsportsdock, playtomic, "
            "matchi, gladstonego, clubspark, mytimeactive, placesleisure"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Crawl and report counts without writing to the database",
    )
    args = parser.parse_args(argv)

    provider_names = _selected_providers(args.only)
    scope = "main" if not args.only else "-".join(sorted(provider_names))
    lock = _acquire_lock(scope)
    if lock is None:
        logging.warning("Previous residential crawl still running; skipping this tick")
        return 0

    state = _load_state()

    blocked_until = state.get("playtomic", {}).get("blocked_until", 0)
    if blocked_until > time.time() and "playtomic" in provider_names:
        logging.warning(
            "Playtomic cooldown active until "
            f"{datetime.fromtimestamp(blocked_until):%H:%M}; skipping this run"
        )
        provider_names = [name for name in provider_names if name != "playtomic"]
        if not provider_names:
            return 0

    if not args.only:
        requested = provider_names
        provider_names = _due_providers(state, time.time(), requested)
        skipped = [name for name in requested if name not in provider_names]
        if skipped:
            logging.info(f"Not due yet (hourly cadence): {', '.join(skipped)}")
        if not provider_names:
            logging.info("Nothing due this tick, exiting")
            return 0

    today = date.today()
    dates_by_sport = {
        sport: [today + timedelta(days=i) for i in range(days)]
        for sport, days in HORIZON_DAYS.items()
    }
    playtomic_dates, playtomic_mid_due, playtomic_long_due = _playtomic_dates(
        state, today, time.time()
    )

    logging.info(
        f"Residential crawl starting for: {', '.join(provider_names)} "
        f"(ENV={os.environ.get('ENV')}, dry_run={args.dry_run})"
    )
    run_started = datetime.now()
    started = time.monotonic()

    try:
        labelled = asyncio.run(
            _crawl(provider_names, dates_by_sport, playtomic_dates, state)
        )
    except Exception as exc:
        logging.error(f"Residential crawl failed: {exc!r}")
        _record_attempts(state, provider_names, {}, args.dry_run)
        return 1

    slots_by_sport: Dict[str, List[UnifiedParserSchema]] = {}
    counts: List[str] = []
    counts_by_provider: Dict[str, Dict[str, int]] = {}
    for name, label, sport, result in labelled:
        counts.append(f"{label}/{sport}={len(result)}")
        counts_by_provider.setdefault(name, {})[sport] = len(result)
        slots_by_sport.setdefault(sport, []).extend(result)

    for sport in sorted(slots_by_sport):
        slots = fill_estimated_prices(flatten_responses([slots_by_sport[sport]]))
        _write_sport(sport, slots, run_started, args.dry_run)

    _record_attempts(
        state,
        provider_names,
        counts_by_provider,
        args.dry_run,
        playtomic_mid_due=playtomic_mid_due,
        playtomic_long_due=playtomic_long_due,
    )

    logging.info(
        f"Residential crawl finished in {time.monotonic() - started:.0f}s :: "
        + ", ".join(counts)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
