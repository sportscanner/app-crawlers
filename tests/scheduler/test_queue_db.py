from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import text

from sportscanner.crawlers.parsers.core.fetch_failures import FetchFailure
from sportscanner.scheduler import worker as worker_module
from sportscanner.scheduler.providers import FetchOutcome
from sportscanner.scheduler.queue import (
    JobPlan,
    claim_jobs,
    complete_job,
    enqueue_jobs,
)


def _plan(prefix: str, venue: str, day, run_after: datetime) -> JobPlan:
    return JobPlan(
        provider=prefix,
        sport="padel",
        composite_key=venue,
        slot_date=day,
        tier=1,
        run_after=run_after,
    )


def _rows(engine, prefix: str):
    with engine.connect() as conn:
        return {
            (row["composite_key"], row["slot_date"]): dict(row)
            for row in conn.execute(
                text(
                    "SELECT * FROM public.crawl_job WHERE provider = :provider "
                    "ORDER BY id"
                ),
                {"provider": prefix},
            ).mappings()
        }


def _status(engine, prefix: str, venue: str, day):
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT * FROM public.crawl_source_status "
                    "WHERE provider = :provider AND composite_key = :venue "
                    "AND slot_date = :day"
                ),
                {"provider": prefix, "venue": venue, "day": day},
            )
            .mappings()
            .first()
        )
    return dict(row) if row else None


def test_enqueue_is_idempotent_and_rearms_only_completed_rows(
    scheduler_engine, queue_prefix
):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    today = now.date()
    venue = "venue-1"
    plans = [
        _plan(queue_prefix, venue, today, now),
        _plan(queue_prefix, venue, today + timedelta(days=1), now),
    ]

    assert enqueue_jobs(scheduler_engine, plans) == 2
    # Re-running before anything runs must not insert duplicates or touch rows.
    assert enqueue_jobs(scheduler_engine, plans) == 0
    assert len(_rows(scheduler_engine, queue_prefix)) == 2

    first_day, second_day = today, today + timedelta(days=1)
    first = _rows(scheduler_engine, queue_prefix)[(venue, first_day)]
    complete_job(scheduler_engine, first, now, slots_found=0)

    # A retry backoff written by a worker must survive the next scheduler tick.
    future = now + timedelta(hours=1)
    with scheduler_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE public.crawl_job SET run_after = :future "
                "WHERE provider = :provider AND slot_date = :day"
            ),
            {"future": future, "provider": queue_prefix, "day": second_day},
        )

    assert enqueue_jobs(scheduler_engine, plans) == 1

    rows = _rows(scheduler_engine, queue_prefix)
    assert len(rows) == 2
    assert rows[(venue, first_day)]["completed_at"] is None
    assert rows[(venue, first_day)]["run_after"] == now
    assert rows[(venue, second_day)]["run_after"] == future


def test_two_workers_claim_disjoint_jobs(scheduler_engine, queue_prefix):
    now = datetime.now(timezone.utc)
    today = now.date()
    plans = [
        _plan(queue_prefix, "venue-a", today, now - timedelta(minutes=1)),
        _plan(queue_prefix, "venue-b", today, now - timedelta(minutes=1)),
    ]
    enqueue_jobs(scheduler_engine, plans)

    first = claim_jobs(scheduler_engine, [queue_prefix], 1, now, "worker-a", 5, 600)
    second = claim_jobs(scheduler_engine, [queue_prefix], 1, now, "worker-b", 5, 600)

    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["id"] != second[0]["id"]
    assert first[0]["attempts"] == 1
    assert second[0]["attempts"] == 1
    assert (
        claim_jobs(scheduler_engine, [queue_prefix], 10, now, "worker-c", 5, 600) == []
    )


def test_claim_skips_rows_locked_by_another_transaction(scheduler_engine, queue_prefix):
    now = datetime.now(timezone.utc)
    venue = "venue-locked"
    enqueue_jobs(
        scheduler_engine,
        [_plan(queue_prefix, venue, now.date(), now - timedelta(minutes=1))],
    )

    conn = scheduler_engine.connect()
    transaction = conn.begin()
    try:
        locked_id = conn.execute(
            text(
                "SELECT id FROM public.crawl_job WHERE provider = :provider "
                "FOR UPDATE"
            ),
            {"provider": queue_prefix},
        ).scalar_one()
        assert (
            claim_jobs(scheduler_engine, [queue_prefix], 1, now, "worker-b", 5, 600)
            == []
        )
    finally:
        transaction.rollback()
        conn.close()

    claimed = claim_jobs(scheduler_engine, [queue_prefix], 1, now, "worker-b", 5, 600)
    assert [job["id"] for job in claimed] == [locked_id]


def test_stale_claim_is_recoverable_and_attempts_are_bounded(
    scheduler_engine, queue_prefix
):
    now = datetime.now(timezone.utc)
    venue = "venue-stale"
    enqueue_jobs(
        scheduler_engine,
        [_plan(queue_prefix, venue, now.date(), now - timedelta(minutes=1))],
    )

    first = claim_jobs(scheduler_engine, [queue_prefix], 1, now, "worker-a", 5, 600)
    assert first[0]["attempts"] == 1

    stale_at = now - timedelta(seconds=1200)
    with scheduler_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE public.crawl_job SET claimed_at = :stale_at, attempts = 5 "
                "WHERE id = :id"
            ),
            {"stale_at": stale_at, "id": first[0]["id"]},
        )

    recovered = claim_jobs(scheduler_engine, [queue_prefix], 1, now, "worker-b", 5, 600)
    assert len(recovered) == 1
    assert recovered[0]["id"] == first[0]["id"]
    assert recovered[0]["attempts"] == 1


def test_zero_slots_is_success_but_fetch_error_is_not(
    scheduler_engine, queue_prefix, padel_venue_key, monkeypatch
):
    now = datetime.now(timezone.utc)
    today = now.date()
    plans = [
        _plan(queue_prefix, padel_venue_key, today, now - timedelta(minutes=1)),
        _plan(
            queue_prefix,
            padel_venue_key,
            today + timedelta(days=1),
            now - timedelta(minutes=1),
        ),
    ]
    enqueue_jobs(scheduler_engine, plans)

    fake_spec = SimpleNamespace(
        key=queue_prefix,
        crawlers={"padel": lambda: None},
        max_concurrent=1,
        min_interval_seconds=0.0,
    )
    monkeypatch.setattr(worker_module, "get_provider", lambda key: fake_spec)
    monkeypatch.setattr(
        worker_module, "provider_for_website", lambda website: fake_spec
    )
    monkeypatch.setattr(
        worker_module,
        "insert_records_to_table",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("zero slots should not write rows")
        ),
    )

    job = claim_jobs(scheduler_engine, [queue_prefix], 1, now, "worker-a", 5, 600)[0]
    monkeypatch.setattr(
        worker_module,
        "fetch_venue_date",
        lambda provider, sport, venue, slot_date: FetchOutcome(slots=[], failures=[]),
    )
    result = worker_module.execute_job(scheduler_engine, job, max_attempts=5, now=now)
    assert result.ok
    assert result.slots_found == 0
    status = _status(scheduler_engine, queue_prefix, padel_venue_key, today)
    assert status["last_success_at"] is not None
    assert status["slots_found"] == 0
    row = _rows(scheduler_engine, queue_prefix)[(padel_venue_key, today)]
    assert row["completed_at"] is not None

    failing_day = today + timedelta(days=1)
    job = claim_jobs(scheduler_engine, [queue_prefix], 1, now, "worker-a", 5, 600)[0]
    monkeypatch.setattr(
        worker_module,
        "fetch_venue_date",
        lambda provider, sport, venue, slot_date: FetchOutcome(
            slots=[],
            failures=[
                FetchFailure(
                    "HTTP 429",
                    status=429,
                    retryable=True,
                    retry_after_seconds=5,
                )
            ],
        ),
    )
    result = worker_module.execute_job(scheduler_engine, job, max_attempts=5, now=now)
    assert not result.ok
    assert result.retry_at is not None
    status = _status(scheduler_engine, queue_prefix, padel_venue_key, failing_day)
    assert status["last_success_at"] is None
    assert status["last_attempt_at"] is not None
    assert "429" in status["last_error"]
    row = _rows(scheduler_engine, queue_prefix)[(padel_venue_key, failing_day)]
    assert row["completed_at"] is None
    assert row["run_after"] > now
