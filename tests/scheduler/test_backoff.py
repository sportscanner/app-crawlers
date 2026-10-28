import random
from datetime import datetime, timedelta, timezone

from sportscanner.scheduler.queue import backoff_seconds, retry_decision


def test_exponential_backoff_grows_and_caps():
    rng = random.Random(0)
    first = backoff_seconds(1, jitter_ratio=0.0, rng=rng)
    second = backoff_seconds(2, jitter_ratio=0.0, rng=rng)
    third = backoff_seconds(3, jitter_ratio=0.0, rng=rng)
    capped = backoff_seconds(20, jitter_ratio=0.0, rng=rng)

    assert (first, second, third) == (30.0, 60.0, 120.0)
    assert capped == 1800.0


def test_backoff_jitter_stays_within_bounds():
    rng = random.Random(42)
    for _ in range(50):
        delay = backoff_seconds(2, jitter_ratio=0.2, rng=rng)
        assert 48.0 <= delay <= 72.0


def test_retry_after_429_is_honoured():
    rng = random.Random(0)
    delay = backoff_seconds(1, retry_after_seconds=120, rng=rng)
    assert 120.0 <= delay <= 144.0


def test_retry_decision_exhausts_then_cools_down():
    now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    rng = random.Random(0)

    retry = retry_decision(1, now=now, max_attempts=5, rng=rng)
    assert not retry.exhausted
    assert retry.attempts == 1
    assert retry.run_after > now

    exhausted = retry_decision(5, now=now, max_attempts=5, rng=rng)
    assert exhausted.exhausted
    assert exhausted.attempts == 0
    assert exhausted.run_after >= now + timedelta(seconds=3600)


def test_retry_after_takes_priority_over_short_backoff():
    now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    decision = retry_decision(
        1, now=now, max_attempts=5, retry_after_seconds=600, rng=random.Random(0)
    )
    assert decision.run_after >= now + timedelta(seconds=600)
