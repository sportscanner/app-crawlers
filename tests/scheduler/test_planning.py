from datetime import date, datetime, timedelta, timezone

from sportscanner.scheduler.queue import plan_jobs
from sportscanner.storage.postgres.tables import SportsVenue


def _venue(composite_key: str, website: str, sports: list[str]) -> SportsVenue:
    return SportsVenue(
        composite_key=composite_key,
        organisation="Test",
        organisation_website=website,
        venue_name="Test venue",
        slug="test-venue",
        postcode="E1 1AA",
        address="1 Test Street",
        latitude=51.5,
        longitude=-0.1,
        sports=sports,
    )


def test_plan_jobs_covers_horizon_and_tiers():
    now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    venue = _venue("abc12345", "https://playtomic.com", ["padel", "tennis"])
    plans = plan_jobs([venue], {}, now, horizon_days=10)

    # One row per provider/venue/date; multi-sport venues fetch all sports.
    assert len(plans) == 10
    by_date = {plan.slot_date: plan for plan in plans}
    assert all(plan.sport == "padel,tennis" for plan in plans)
    assert by_date[date(2026, 10, 28)].tier == 1
    assert by_date[date(2026, 10, 29)].tier == 1
    assert by_date[date(2026, 10, 30)].tier == 2
    assert by_date[date(2026, 11, 3)].tier == 2
    assert by_date[date(2026, 11, 4)].tier == 3
    assert by_date[date(2026, 11, 6)].tier == 3
    assert all(plan.run_after == now for plan in plans)


def test_plan_jobs_uses_last_success_per_venue_date():
    now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    venue = _venue("abc12345", "https://playtomic.com", ["padel"])
    today = now.date()
    last_success = {
        ("playtomic", "abc12345", today): now - timedelta(minutes=5),
        ("playtomic", "abc12345", today + timedelta(days=3)): now - timedelta(hours=2),
    }
    plans = {plan.slot_date: plan for plan in plan_jobs([venue], last_success, now)}
    assert plans[today].run_after == now + timedelta(minutes=10)
    # day 3 is tier 2, last success was 2 hours ago: overdue, so due now.
    assert plans[today + timedelta(days=3)].run_after < now


def test_plan_jobs_filters_and_skips_unknown_providers():
    now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    playtomic = _venue("abc12345", "https://playtomic.com", ["padel"])
    unknown = _venue("def67890", "https://unknown.example", ["padel"])
    unsupported = _venue("ghi00000", "https://www.better.org.uk", ["padel"])

    plans = plan_jobs(
        [playtomic, unknown, unsupported], {}, now, providers={"playtomic"}
    )
    assert {(plan.provider, plan.sport) for plan in plans} == {("playtomic", "padel")}

    multi_sport = _venue("jkl11111", "https://playtomic.com", ["padel", "tennis"])
    tennis_only = plan_jobs([multi_sport], {}, now, sports={"tennis"})
    assert {(plan.provider, plan.sport) for plan in tennis_only} == {
        ("playtomic", "tennis")
    }
