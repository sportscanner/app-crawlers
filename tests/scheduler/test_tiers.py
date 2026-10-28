from datetime import date, datetime, timedelta, timezone

import pytest

from sportscanner.scheduler.tiers import (
    DEFAULT_HORIZON_DAYS,
    horizon_dates,
    next_due,
    tier_for_date,
    tier_for_day_offset,
)


def test_tier_boundaries():
    assert [tier_for_day_offset(offset) for offset in range(10)] == [
        1,
        1,
        2,
        2,
        2,
        2,
        2,
        3,
        3,
        3,
    ]
    assert tier_for_day_offset(10) is None
    with pytest.raises(ValueError):
        tier_for_day_offset(-1)


def test_tier_for_date_uses_today():
    today = date(2026, 10, 28)
    assert tier_for_date(today, today) == 1
    assert tier_for_date(today + timedelta(days=1), today) == 1
    assert tier_for_date(today + timedelta(days=2), today) == 2
    assert tier_for_date(today + timedelta(days=6), today) == 2
    assert tier_for_date(today + timedelta(days=7), today) == 3
    assert tier_for_date(today + timedelta(days=9), today) == 3
    assert tier_for_date(today + timedelta(days=10), today) is None


def test_next_due_without_success_is_now():
    now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    assert next_due(1, now) == now
    assert next_due(2, now, None) == now
    assert next_due(3, now, None) == now


def test_next_due_measured_from_last_success_not_attempt():
    now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    last_success = now - timedelta(minutes=14)

    assert next_due(1, now, last_success) == last_success + timedelta(minutes=15)
    assert next_due(2, now, last_success) == last_success + timedelta(hours=1)
    assert next_due(3, now, last_success) == last_success + timedelta(hours=6)

    # A stale success leaves run_after in the past, which means "due now".
    stale = now - timedelta(hours=2)
    assert next_due(1, now, stale) < now


def test_next_due_rejects_unknown_tier():
    with pytest.raises(ValueError):
        next_due(4, datetime.now(timezone.utc))


def test_horizon_dates_default_and_bounds():
    today = date(2026, 10, 28)
    dates = horizon_dates(today)
    assert len(dates) == DEFAULT_HORIZON_DAYS == 10
    assert dates[0] == today
    assert dates[-1] == today + timedelta(days=9)
    with pytest.raises(ValueError):
        horizon_dates(today, 0)
    with pytest.raises(ValueError):
        horizon_dates(today, 11)
