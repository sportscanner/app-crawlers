"""Provider-scoped crawl worker.

    python -m sportscanner.scheduler.worker --provider playtomic --once

Claims due jobs with FOR UPDATE SKIP LOCKED, runs the existing provider fetch
for one (venue, date), writes successful slots through
`insert_records_to_table`, and updates `crawl_source_status`. A fetch failure
is never recorded as a success: the claim is released with backoff, bounded by
`attempts`, and a stale claim is reclaimable after `--stale-after` seconds.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import Engine
from sqlmodel import Session

from sportscanner.logger import logging
from sportscanner.scheduler.providers import (
    PROVIDERS,
    SPORT_TABLES,
    FetchOutcome,
    fetch_venue_date,
    get_provider,
    provider_for_website,
)
from sportscanner.scheduler.queue import (
    claim_jobs,
    complete_job,
    complete_permanent_failure,
    fail_job,
    peek_due_jobs,
)
from sportscanner.storage.postgres.database import engine as default_engine
from sportscanner.storage.postgres.database import insert_records_to_table
from sportscanner.storage.postgres.tables import SportsVenue

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_STALE_AFTER_SECONDS = 600


@dataclass
class JobResult:
    job_id: int
    provider: str
    composite_key: str
    slot_date: object
    ok: bool
    slots_found: int
    error: Optional[str] = None
    retry_at: Optional[datetime] = None


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def execute_job(
    engine: Engine,
    job: dict,
    *,
    max_attempts: int,
    now: Optional[datetime] = None,
    rng: Optional[random.Random] = None,
) -> JobResult:
    """Run one claimed job synchronously. Never raises for a fetch failure."""
    now = now or datetime.now(timezone.utc)
    provider = job["provider"]
    sports = [sport.strip() for sport in job["sport"].split(",") if sport.strip()]
    composite_key = job["composite_key"]
    slot_date = job["slot_date"]

    try:
        spec = get_provider(provider)
    except KeyError as exc:
        complete_permanent_failure(engine, job, now, str(exc))
        return JobResult(
            job_id=job["id"],
            provider=provider,
            composite_key=composite_key,
            slot_date=slot_date,
            ok=False,
            slots_found=0,
            error=str(exc),
        )

    unsupported = [
        sport
        for sport in sports
        if sport not in spec.crawlers or sport not in SPORT_TABLES
    ]
    if not sports or unsupported:
        error = f"{provider} does not support sport(s) {unsupported or sports!r}"
        complete_permanent_failure(engine, job, now, error)
        return JobResult(
            job_id=job["id"],
            provider=provider,
            composite_key=composite_key,
            slot_date=slot_date,
            ok=False,
            slots_found=0,
            error=error,
        )

    with Session(engine) as session:
        venue = session.get(SportsVenue, composite_key)
    if venue is None:
        error = f"Venue {composite_key!r} not found in sportsvenue"
        complete_permanent_failure(engine, job, now, error)
        return JobResult(
            job_id=job["id"],
            provider=provider,
            composite_key=composite_key,
            slot_date=slot_date,
            ok=False,
            slots_found=0,
            error=error,
        )

    venue_provider = provider_for_website(venue.organisation_website)
    if venue_provider is None or venue_provider.key != provider:
        error = (
            f"Venue {composite_key!r} belongs to "
            f"{venue_provider.key if venue_provider else 'an unknown provider'}, "
            f"not {provider!r}"
        )
        complete_permanent_failure(engine, job, now, error)
        return JobResult(
            job_id=job["id"],
            provider=provider,
            composite_key=composite_key,
            slot_date=slot_date,
            ok=False,
            slots_found=0,
            error=error,
        )
    missing_sports = [sport for sport in sports if sport not in venue.sports]
    if missing_sports:
        error = f"Venue {composite_key!r} does not offer {missing_sports!r}"
        complete_permanent_failure(engine, job, now, error)
        return JobResult(
            job_id=job["id"],
            provider=provider,
            composite_key=composite_key,
            slot_date=slot_date,
            ok=False,
            slots_found=0,
            error=error,
        )

    outcomes = {
        sport: fetch_venue_date(provider, sport, venue, slot_date) for sport in sports
    }
    failures = [
        failure
        for outcome in outcomes.values()
        if not outcome.ok
        for failure in outcome.failures
    ]
    combined = FetchOutcome(
        slots=[
            slot
            for outcome in outcomes.values()
            if outcome.ok
            for slot in outcome.slots
        ],
        failures=failures,
    )

    write_error: Optional[str] = None
    try:
        for sport, outcome in outcomes.items():
            if outcome.ok and outcome.slots:
                insert_records_to_table(outcome.slots, SPORT_TABLES[sport])
    except Exception as exc:
        write_error = f"DB write failed: {type(exc).__name__}: {exc!r}"

    if failures or write_error:
        error = write_error or combined.error_message or f"{provider} fetch failed"
        decision = fail_job(
            engine,
            job,
            now,
            error,
            max_attempts=max_attempts,
            retry_after_seconds=combined.retry_after_seconds,
            rng=rng,
        )
        logging.warning(
            f"{provider} {composite_key} {slot_date}: fetch failed "
            f"(attempt {job['attempts']}/{max_attempts}) - retry at "
            f"{decision.run_after.isoformat()}: {error}"
        )
        return JobResult(
            job_id=job["id"],
            provider=provider,
            composite_key=composite_key,
            slot_date=slot_date,
            ok=False,
            slots_found=len(combined.slots),
            error=error,
            retry_at=decision.run_after,
        )

    # A fetched, genuinely empty result is a success and advances freshness.
    complete_job(engine, job, now, slots_found=len(combined.slots))
    logging.info(
        f"{provider} {composite_key} {slot_date}: {len(combined.slots)} slot(s)"
    )
    return JobResult(
        job_id=job["id"],
        provider=provider,
        composite_key=composite_key,
        slot_date=slot_date,
        ok=True,
        slots_found=len(combined.slots),
    )


def dry_run(
    engine: Engine,
    providers: Sequence[str],
    *,
    limit: int,
    max_attempts: int,
    stale_after_seconds: int,
) -> int:
    now = datetime.now(timezone.utc)
    jobs = peek_due_jobs(
        engine,
        providers,
        limit,
        now,
        max_attempts,
        stale_after_seconds,
    )
    for job in jobs:
        logging.info(
            f"[dry-run] {job['provider']} {job['sport']} "
            f"{job['composite_key']} {job['slot_date']} "
            f"(attempts {job['attempts']}, due {job['run_after'].isoformat()})"
        )
    logging.success(f"[dry-run] {len(jobs)} due job(s); nothing claimed")
    return len(jobs)


async def run_worker(
    engine: Engine,
    *,
    providers: Optional[Sequence[str]] = None,
    workers: int = 2,
    once: bool = False,
    is_dry_run: bool = False,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
    poll_interval: float = 0.5,
) -> list[JobResult]:
    provider_keys = list(providers) if providers else sorted(PROVIDERS)
    unknown = sorted(set(provider_keys) - set(PROVIDERS))
    if unknown:
        raise SystemExit(
            f"Unknown provider(s): {', '.join(unknown)}. "
            f"Known: {', '.join(sorted(PROVIDERS))}"
        )
    if workers < 1:
        raise SystemExit("--workers must be at least 1")
    if max_attempts < 1:
        raise SystemExit("--max-attempts must be at least 1")

    if is_dry_run:
        dry_run(
            engine,
            provider_keys,
            limit=max(workers, 1) * max(len(provider_keys), 1) * 10,
            max_attempts=max_attempts,
            stale_after_seconds=stale_after_seconds,
        )
        return []

    worker_id = _worker_id()
    caps = {
        key: max(1, min(workers, get_provider(key).max_concurrent))
        for key in provider_keys
    }
    in_flight = {key: 0 for key in provider_keys}
    next_start = {key: 0.0 for key in provider_keys}
    tasks: set[asyncio.Task] = set()
    task_providers: dict[asyncio.Task, str] = {}
    results: list[JobResult] = []

    logging.info(
        f"Worker {worker_id} started for {', '.join(provider_keys)} "
        f"(caps: {caps}, once={once})"
    )

    def _collect(done_tasks) -> None:
        for task in done_tasks:
            provider = task_providers.pop(task, None)
            if provider in in_flight:
                in_flight[provider] -= 1
            tasks.discard(task)
            try:
                results.append(task.result())
            except asyncio.CancelledError:
                logging.warning("Job task cancelled")
            except Exception as exc:
                logging.error(f"Job task raised: {type(exc).__name__}: {exc!r}")

    while True:
        claimed_any = False
        for provider in provider_keys:
            if in_flight[provider] >= caps[provider]:
                continue
            if time.monotonic() < next_start[provider]:
                continue
            now = datetime.now(timezone.utc)
            jobs = claim_jobs(
                engine,
                [provider],
                1,
                now,
                worker_id,
                max_attempts,
                stale_after_seconds,
            )
            if not jobs:
                continue
            job = jobs[0]
            claimed_any = True
            next_start[provider] = (
                time.monotonic() + get_provider(provider).min_interval_seconds
            )
            in_flight[provider] += 1
            task = asyncio.create_task(
                asyncio.to_thread(
                    execute_job,
                    engine,
                    job,
                    max_attempts=max_attempts,
                )
            )
            task_providers[task] = provider
            tasks.add(task)

        if tasks:
            done, _ = await asyncio.wait(
                tasks, timeout=poll_interval, return_when=asyncio.FIRST_COMPLETED
            )
            _collect(done)
            continue

        if once and not claimed_any:
            break
        if once and claimed_any:
            # One pass has been claimed; keep looping until those jobs finish.
            continue
        await asyncio.sleep(poll_interval)

    if tasks:
        done, _ = await asyncio.wait(tasks)
        _collect(done)

    succeeded = sum(1 for result in results if result.ok)
    logging.success(
        f"Worker {worker_id} stopped: {len(results)} job(s), "
        f"{succeeded} succeeded, {len(results) - succeeded} failed"
    )
    return results


def _csv(value: Optional[str]) -> Optional[list[str]]:
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Claim and run due crawl jobs from PostgreSQL"
    )
    parser.add_argument(
        "--provider",
        help="Comma-separated provider keys (default: all registered providers)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Maximum concurrent jobs per provider (capped by the provider budget)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Drain currently due jobs, then exit (default: keep polling)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show due jobs without claiming, fetching or writing",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
        help="Retries per job before a longer cooldown",
    )
    parser.add_argument(
        "--stale-after",
        type=int,
        default=DEFAULT_STALE_AFTER_SECONDS,
        help="Seconds after which a crashed worker's claim is reclaimable",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Seconds between queue polls when idle",
    )
    args = parser.parse_args(argv)

    asyncio.run(
        run_worker(
            default_engine,
            providers=_csv(args.provider),
            workers=args.workers,
            once=args.once,
            is_dry_run=args.dry_run,
            max_attempts=args.max_attempts,
            stale_after_seconds=args.stale_after,
            poll_interval=args.poll_interval,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
