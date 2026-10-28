"""Pure freshness-tier maths for the crawl queue.

Tiers are keyed by how far a slot date is from today:

    1: today and tomorrow      every 15 minutes
    2: days 2 to 6             hourly
    3: days 7 to 9             every 6 hours

Nothing outside that 10-day horizon is scheduled. Freshness is measured from
the last *successful* observation, never from the last attempted job, so a
failed crawl cannot make a row look fresh.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

TIER_INTERVALS: dict[int, timedelta] = {
    1: timedelta(minutes=15),
    2: timedelta(hours=1),
    3: timedelta(hours=6),
}

TIER_1_LAST_DAY_OFFSET = 1
TIER_2_LAST_DAY_OFFSET = 6
TIER_3_LAST_DAY_OFFSET = 9

DEFAULT_HORIZON_DAYS = TIER_3_LAST_DAY_OFFSET + 1


def tier_for_day_offset(day_offset: int) -> Optional[int]:
    """Return the freshness tier for a date offset from today, or None."""
    if day_offset < 0:
        raise ValueError("day_offset cannot be negative")
    if day_offset <= TIER_1_LAST_DAY_OFFSET:
        return 1
    if day_offset <= TIER_2_LAST_DAY_OFFSET:
        return 2
    if day_offset <= TIER_3_LAST_DAY_OFFSET:
        return 3
    return None


def tier_for_date(slot_date: date, today: date) -> Optional[int]:
    """Return the freshness tier for `slot_date`, or None outside the horizon."""
    return tier_for_day_offset((slot_date - today).days)


def next_due(
    tier: int,
    now: datetime,
    last_success_at: Optional[datetime] = None,
) -> datetime:
    """Return when a tier's next poll is due.

    No prior success means the job is due immediately. Otherwise the next poll
    is one cadence after the last successful observation. A stale success time
    therefore yields a `run_after` in the past, which is exactly what makes the
    job immediately claimable.
    """
    try:
        interval = TIER_INTERVALS[tier]
    except KeyError as exc:
        raise ValueError(f"Unknown freshness tier: {tier!r}") from exc
    if last_success_at is None:
        return now
    return last_success_at + interval


def horizon_dates(today: date, horizon_days: int = DEFAULT_HORIZON_DAYS) -> list[date]:
    """Dates covered by the scheduler, from today through the horizon."""
    if horizon_days < 1:
        raise ValueError("horizon_days must be at least 1")
    if horizon_days > DEFAULT_HORIZON_DAYS:
        raise ValueError(
            f"horizon_days cannot exceed {DEFAULT_HORIZON_DAYS} "
            "(tier 3 ends at day 9)"
        )
    return [today + timedelta(days=offset) for offset in range(horizon_days)]
