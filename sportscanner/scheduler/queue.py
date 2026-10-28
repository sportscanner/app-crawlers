"""Durable crawl queue operations.

The queue lives in PostgreSQL. Enqueue is a single upsert per provider batch;
claiming uses SELECT ... FOR UPDATE SKIP LOCKED so multiple workers can pull
from the same queue without a broker. Nothing here is imported by the API.
"""

from __future__ import annotations

import random
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Mapping, Optional, Sequence

from sqlalchemy import Engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from sportscanner.logger import logging
from sportscanner.scheduler.providers import (
    get_provider,
    normalise_website,
    provider_for_website,
)
from sportscanner.scheduler.tiers import (
    DEFAULT_HORIZON_DAYS,
    horizon_dates,
    next_due,
    tier_for_date,
)
from sportscanner.storage.postgres.tables import (
    CrawlJob,
    CrawlSourceStatus,
    SportsVenue,
)

ENQUEUE_ADVISORY_LOCK_KEY = 0x5C0A11  # arbitrary, private to this scheduler


@dataclass(frozen=True)
class JobPlan:
    provider: str
    sport: str
    composite_key: str
    slot_date: date
    tier: int
    run_after: datetime


@dataclass(frozen=True)
class RetryDecision:
    run_after: datetime
    attempts: int
    exhausted: bool


def plan_jobs(
    venues: Iterable[SportsVenue],
    last_success: Mapping[tuple[str, str, date], Optional[datetime]],
    now: datetime,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    providers: Optional[set[str]] = None,
    sports: Optional[set[str]] = None,
) -> list[JobPlan]:
    """Pure planning step: every (provider, venue, date) in the horizon.

    The queue's uniqueness constraint is (provider, composite_key, slot_date),
    so a venue that offers several sports under the same provider gets one job
    whose `sport` field is a comma-separated list. `last_success` is keyed by
    (provider, composite_key, slot_date). A missing or None value means the
    pair has never succeeded, so it is due now.
    """
    today = now.date()
    dates = horizon_dates(today, horizon_days)
    plans: dict[tuple[str, str, date], JobPlan] = {}

    for venue in venues:
        spec = provider_for_website(venue.organisation_website)
        if spec is None:
            continue
        if providers is not None and spec.key not in providers:
            continue
        venue_sports = sorted(
            sport
            for sport in set(venue.sports)
            if sport in spec.crawlers and (sports is None or sport in sports)
        )
        if not venue_sports:
            continue
        # The queue is unique on (provider, composite_key, slot_date), so one
        # job fetches every supported sport this venue offers for that date.
        sport_field = ",".join(venue_sports)
        for slot_date in dates:
            tier = tier_for_date(slot_date, today)
            if tier is None:
                continue
            key = (spec.key, venue.composite_key, slot_date)
            run_after = next_due(tier, now, last_success.get(key))
            plans[key] = JobPlan(
                provider=spec.key,
                sport=sport_field,
                composite_key=venue.composite_key,
                slot_date=slot_date,
                tier=tier,
                run_after=run_after,
            )

    return sorted(
        plans.values(),
        key=lambda plan: (
            plan.provider,
            plan.composite_key,
            plan.slot_date,
        ),
    )


def _chunks(values: Sequence[JobPlan], size: int = 1000) -> Iterable[Sequence[JobPlan]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def enqueue_jobs(
    engine: Engine,
    plans: Sequence[JobPlan],
    dry_run: bool = False,
) -> int:
    """Upsert planned jobs, never resetting an in-flight or due row.

    New rows are inserted. A completed row is re-armed for its next tier. A
    pending row is left alone, so a retry backoff written by a worker cannot be
    overwritten by the next scheduler tick.
    """
    if not plans:
        return 0

    total = 0
    if dry_run:
        for chunk in _chunks(plans):
            for plan in chunk:
                logging.info(
                    f"[dry-run] {plan.provider} {plan.sport} "
                    f"{plan.composite_key} {plan.slot_date} tier {plan.tier} "
                    f"run_after {plan.run_after.isoformat()}"
                )
            total += len(chunk)
        return total

    table = CrawlJob.__table__
    for chunk in _chunks(plans):
        rows = [
            dict(
                provider=plan.provider,
                sport=plan.sport,
                composite_key=plan.composite_key,
                slot_date=plan.slot_date,
                tier=plan.tier,
                run_after=plan.run_after,
            )
            for plan in chunk
        ]
        stmt = pg_insert(table).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                table.c.provider,
                table.c.composite_key,
                table.c.slot_date,
            ],
            set_={
                "sport": stmt.excluded.sport,
                "tier": stmt.excluded.tier,
                "run_after": stmt.excluded.run_after,
                "claimed_at": None,
                "claimed_by": None,
                "attempts": 0,
                "last_error": None,
                "completed_at": None,
            },
            where=(
                table.c.completed_at.is_not(None)
                & table.c.claimed_at.is_(None)
                & table.c.last_error.is_(None)
            ),
        )
        with engine.begin() as conn:
            result = conn.execute(stmt)
            total += result.rowcount or 0
    return total


@contextmanager
def enqueue_lock(engine: Engine):
    """Prevent two schedulers running the same enqueue tick concurrently."""
    with engine.connect() as conn:
        acquired = conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": ENQUEUE_ADVISORY_LOCK_KEY},
        ).scalar()
        try:
            yield bool(acquired)
        finally:
            if acquired:
                conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"),
                    {"key": ENQUEUE_ADVISORY_LOCK_KEY},
                )


def load_venues(engine: Engine, provider: str) -> list[SportsVenue]:
    """One cheap query per provider per scheduler tick."""
    spec = get_provider(provider)
    raw = spec.organisation_website
    candidates = {raw, raw.rstrip("/"), raw.rstrip("/") + "/"}
    with Session(engine) as session:
        rows = session.exec(
            select(SportsVenue).where(SportsVenue.organisation_website.in_(candidates))
        ).all()
    target = normalise_website(raw)
    return [
        venue
        for venue in rows
        if normalise_website(venue.organisation_website) == target
    ]


def load_last_success(
    engine: Engine,
    provider: str,
    start_date: date,
    end_date: date,
) -> dict[tuple[str, str, date], Optional[datetime]]:
    """One cheap query per provider: freshness keyed by venue/date."""
    with Session(engine) as session:
        rows = session.exec(
            select(
                CrawlSourceStatus.composite_key,
                CrawlSourceStatus.slot_date,
                CrawlSourceStatus.last_success_at,
            )
            .where(CrawlSourceStatus.provider == provider)
            .where(CrawlSourceStatus.slot_date >= start_date)
            .where(CrawlSourceStatus.slot_date <= end_date)
        ).all()
    return {
        (provider, composite_key, slot_date): last_success_at
        for composite_key, slot_date, last_success_at in rows
    }


def claim_jobs(
    engine: Engine,
    providers: Sequence[str],
    limit: int,
    now: datetime,
    worker_id: str,
    max_attempts: int,
    stale_after_seconds: int,
) -> list[dict]:
    """Claim due jobs atomically with FOR UPDATE SKIP LOCKED."""
    if not providers or limit < 1:
        return []
    stale_before = now - timedelta(seconds=stale_after_seconds)
    statement = text("""
        WITH due AS (
            SELECT id
            FROM public.crawl_job
            WHERE provider = ANY(:providers)
              AND run_after <= :now
              AND completed_at IS NULL
              AND (
                    (claimed_at IS NULL AND attempts < :max_attempts)
                 OR claimed_at < :stale_before
              )
            ORDER BY run_after ASC, id ASC
            FOR UPDATE SKIP LOCKED
            LIMIT :limit
        )
        UPDATE public.crawl_job AS job
        SET claimed_at = :now,
            claimed_by = :worker_id,
            attempts = CASE
                WHEN job.attempts < :max_attempts THEN job.attempts + 1
                ELSE 1
            END
        FROM due
        WHERE job.id = due.id
        RETURNING job.id, job.provider, job.sport, job.composite_key,
                  job.slot_date, job.tier, job.run_after, job.attempts
        """)
    with engine.begin() as conn:
        rows = (
            conn.execute(
                statement,
                dict(
                    providers=list(providers),
                    now=now,
                    worker_id=worker_id,
                    max_attempts=max_attempts,
                    stale_before=stale_before,
                    limit=limit,
                ),
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def peek_due_jobs(
    engine: Engine,
    providers: Sequence[str],
    limit: int,
    now: datetime,
    max_attempts: int,
    stale_after_seconds: int,
) -> list[dict]:
    """Dry-run view of claimable jobs. Never claims or increments attempts."""
    if not providers:
        return []
    stale_before = now - timedelta(seconds=stale_after_seconds)
    statement = text("""
        SELECT id, provider, sport, composite_key, slot_date, tier,
               run_after, attempts
        FROM public.crawl_job
        WHERE provider = ANY(:providers)
          AND run_after <= :now
          AND completed_at IS NULL
          AND (
                (claimed_at IS NULL AND attempts < :max_attempts)
             OR claimed_at < :stale_before
          )
        ORDER BY run_after ASC, id ASC
        LIMIT :limit
        """)
    with engine.connect() as conn:
        rows = (
            conn.execute(
                statement,
                dict(
                    providers=list(providers),
                    now=now,
                    max_attempts=max_attempts,
                    stale_before=stale_before,
                    limit=limit,
                ),
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def backoff_seconds(
    attempt: int,
    *,
    retry_after_seconds: Optional[float] = None,
    base_seconds: float = 30.0,
    cap_seconds: float = 1800.0,
    jitter_ratio: float = 0.2,
    rng: Optional[random.Random] = None,
) -> float:
    """Exponential backoff with jitter, honouring Retry-After when present."""
    rng = rng or random
    if retry_after_seconds is not None:
        base = max(0.0, retry_after_seconds)
        jitter = base * rng.uniform(0.0, jitter_ratio)
        return base + jitter
    exponent = max(0, attempt - 1)
    raw = min(cap_seconds, base_seconds * (2**exponent))
    jitter = raw * rng.uniform(-jitter_ratio, jitter_ratio)
    return max(1.0, raw + jitter)


def retry_decision(
    attempt: int,
    *,
    now: datetime,
    max_attempts: int,
    retry_after_seconds: Optional[float] = None,
    rng: Optional[random.Random] = None,
    exhausted_cooldown_seconds: float = 3600.0,
) -> RetryDecision:
    """Decide when a failed job becomes claimable again.

    Attempts are incremented at claim time. Once the per-cycle budget is
    exhausted, the row is released with a long cooldown and its attempts reset,
    so another worker can try again later without the row getting stuck.
    """
    if attempt >= max_attempts:
        delay = backoff_seconds(
            attempt,
            retry_after_seconds=retry_after_seconds,
            base_seconds=exhausted_cooldown_seconds,
            cap_seconds=exhausted_cooldown_seconds,
            rng=rng,
        )
        return RetryDecision(
            run_after=now + timedelta(seconds=delay),
            attempts=0,
            exhausted=True,
        )
    delay = backoff_seconds(attempt, retry_after_seconds=retry_after_seconds, rng=rng)
    return RetryDecision(
        run_after=now + timedelta(seconds=delay),
        attempts=attempt,
        exhausted=False,
    )


def _upsert_status_row(
    conn,
    *,
    provider: str,
    composite_key: str,
    sport: str,
    slot_date: date,
    now: datetime,
    success: bool,
    slots_found: Optional[int],
    error: Optional[str],
) -> None:
    table = CrawlSourceStatus.__table__
    stmt = pg_insert(table).values(
        provider=provider,
        composite_key=composite_key,
        sport=sport,
        slot_date=slot_date,
        last_success_at=now if success else None,
        last_attempt_at=now,
        last_error=error,
        slots_found=slots_found if success else None,
    )
    if success:
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                table.c.provider,
                table.c.composite_key,
                table.c.slot_date,
            ],
            set_={
                "sport": stmt.excluded.sport,
                "last_success_at": stmt.excluded.last_success_at,
                "last_attempt_at": stmt.excluded.last_attempt_at,
                "last_error": None,
                "slots_found": stmt.excluded.slots_found,
            },
        )
    else:
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                table.c.provider,
                table.c.composite_key,
                table.c.slot_date,
            ],
            set_={
                "sport": stmt.excluded.sport,
                "last_attempt_at": stmt.excluded.last_attempt_at,
                "last_error": stmt.excluded.last_error,
            },
        )
    conn.execute(stmt)


def complete_job(
    engine: Engine,
    job: Mapping,
    now: datetime,
    slots_found: int,
) -> None:
    """Record a successful fetch, including a genuine zero-slot result."""
    with engine.begin() as conn:
        _upsert_status_row(
            conn,
            provider=job["provider"],
            composite_key=job["composite_key"],
            sport=job["sport"],
            slot_date=job["slot_date"],
            now=now,
            success=True,
            slots_found=slots_found,
            error=None,
        )
        conn.execute(
            text("""
                UPDATE public.crawl_job
                SET claimed_at = NULL,
                    claimed_by = NULL,
                    attempts = 0,
                    last_error = NULL,
                    completed_at = :now
                WHERE id = :id
                """),
            dict(id=job["id"], now=now),
        )


def fail_job(
    engine: Engine,
    job: Mapping,
    now: datetime,
    error: str,
    *,
    max_attempts: int,
    retry_after_seconds: Optional[float] = None,
    rng: Optional[random.Random] = None,
) -> RetryDecision:
    """Release a failed claim for a later retry. Never touches last_success_at."""
    decision = retry_decision(
        int(job["attempts"]),
        now=now,
        max_attempts=max_attempts,
        retry_after_seconds=retry_after_seconds,
        rng=rng,
    )
    with engine.begin() as conn:
        _upsert_status_row(
            conn,
            provider=job["provider"],
            composite_key=job["composite_key"],
            sport=job["sport"],
            slot_date=job["slot_date"],
            now=now,
            success=False,
            slots_found=None,
            error=error,
        )
        conn.execute(
            text("""
                UPDATE public.crawl_job
                SET claimed_at = NULL,
                    claimed_by = NULL,
                    run_after = :run_after,
                    attempts = :attempts,
                    last_error = :error
                WHERE id = :id
                """),
            dict(
                id=job["id"],
                run_after=decision.run_after,
                attempts=decision.attempts,
                error=error[:2000],
            ),
        )
    return decision


def complete_permanent_failure(
    engine: Engine,
    job: Mapping,
    now: datetime,
    error: str,
) -> None:
    """Stop retrying a configuration error (unknown venue/provider/sport)."""
    with engine.begin() as conn:
        _upsert_status_row(
            conn,
            provider=job["provider"],
            composite_key=job["composite_key"],
            sport=job["sport"],
            slot_date=job["slot_date"],
            now=now,
            success=False,
            slots_found=None,
            error=error,
        )
        conn.execute(
            text("""
                UPDATE public.crawl_job
                SET claimed_at = NULL,
                    claimed_by = NULL,
                    attempts = 0,
                    last_error = :error,
                    completed_at = :now
                WHERE id = :id
                """),
            dict(id=job["id"], now=now, error=error[:2000]),
        )
