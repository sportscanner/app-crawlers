import asyncio
from datetime import date

from sportscanner.scheduler import worker as worker_module


def test_once_claims_runs_and_stops(monkeypatch):
    job = {
        "id": 1,
        "provider": "playtomic",
        "sport": "padel",
        "composite_key": "abc12345",
        "slot_date": date(2026, 10, 28),
        "attempts": 1,
    }
    claims = [[job], []]
    executed = []

    def fake_claim(*args, **kwargs):
        return claims.pop(0) if claims else []

    def fake_execute(engine, claimed_job, *, max_attempts, **kwargs):
        executed.append(claimed_job)
        return worker_module.JobResult(
            job_id=claimed_job["id"],
            provider=claimed_job["provider"],
            composite_key=claimed_job["composite_key"],
            slot_date=claimed_job["slot_date"],
            ok=True,
            slots_found=0,
        )

    monkeypatch.setattr(worker_module, "claim_jobs", fake_claim)
    monkeypatch.setattr(worker_module, "execute_job", fake_execute)

    results = asyncio.run(
        worker_module.run_worker(
            None,
            providers=["playtomic"],
            workers=1,
            once=True,
            poll_interval=0.01,
        )
    )

    assert len(executed) == 1
    assert len(results) == 1
    assert results[0].ok
