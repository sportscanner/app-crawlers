from datetime import date

from sportscanner.insights.metrics import (
    MIN_COURT_HOURS_FOR_OCCUPANCY,
    Bucket,
    hourly_profile,
    is_peak,
    venue_stats,
)


def bucket(day=1, hour=10, free=1.0, cap=4.0, pph=40.0, realised=True, key="v1", dow=None, indoor=None):
    d = date(2026, 10, day)
    return Bucket(
        composite_key=key, day=d, dow=dow or d.isoweekday(), hour=hour,
        realised=realised, free=free, cap=cap, pph=pph, indoor=indoor,
    )


def test_peak_definition():
    assert is_peak(1, 7) and is_peak(1, 8) and is_peak(5, 21)
    assert not is_peak(1, 9) and not is_peak(3, 16) and not is_peak(2, 22)
    assert is_peak(6, 11) and is_peak(7, 23)


def test_occupancy_and_value_from_booked_court_hours():
    # 3 days x 10 hours x 4 courts = 120 offered court-hours, 3 booked each hour.
    buckets = [bucket(day=d, hour=h, free=1, cap=4, pph=40) for d in (1, 2, 3) for h in range(8, 18)]
    stats = venue_stats(buckets, {"v1": 4})["v1"]
    assert stats.realised.occupancy == 0.75
    assert stats.realised.value == 90 * 40
    # Three observed days, scaled to a 28-day run-rate.
    assert stats.realised.monthly_value == 90 * 40 / 3 * 28
    assert stats.realised.revpah == 30.0


def test_occupancy_hidden_until_enough_days():
    # Plenty of court-hours, but all from one evening.
    buckets = [bucket(day=1, hour=h, free=0, cap=10) for h in range(17, 23)]
    stats = venue_stats(buckets, {"v1": 10})["v1"]
    assert stats.realised.occupancy is None


def test_occupancy_hidden_below_minimum_sample():
    buckets = [bucket(cap=1, free=0)] * (MIN_COURT_HOURS_FOR_OCCUPANCY - 1)
    stats = venue_stats(buckets, {"v1": 1})["v1"]
    assert stats.realised.occupancy is None
    assert stats.realised.monthly_value is None


def test_free_hours_count_for_occupancy_but_not_value():
    buckets = [bucket(day=d, hour=h, free=0, cap=2, pph=None) for d in (1, 2, 3) for h in range(8, 20)]
    stats = venue_stats(buckets, {"v1": 2})["v1"]
    assert stats.realised.occupancy == 1.0
    assert stats.realised.value == 0
    assert stats.prices.avg_price is None


def test_forward_book_kept_separate_from_realised():
    buckets = [bucket(day=d, hour=h, free=4, cap=4) for d in (1, 2, 3) for h in range(8, 18)] + [
        bucket(day=d, hour=h, free=0, cap=4, realised=False) for d in (4, 5, 6) for h in range(8, 18)
    ]
    stats = venue_stats(buckets, {"v1": 4})["v1"]
    assert stats.realised.occupancy == 0.0
    assert stats.forward.occupancy == 1.0


def test_price_is_weighted_by_hours_offered():
    buckets = [bucket(hour=10, cap=4, pph=20), bucket(hour=11, cap=1, pph=70)]
    stats = venue_stats(buckets, {"v1": 4})["v1"]
    assert stats.prices.avg_price == (4 * 20 + 1 * 70) / 5


def test_indoor_majority_vote():
    buckets = [bucket(indoor=True), bucket(indoor=True), bucket(indoor=False)]
    assert venue_stats(buckets, {})["v1"].indoor is True
    assert venue_stats([bucket()], {})["v1"].indoor is None


def test_hourly_profile_falls_back_to_forward_book():
    profile = hourly_profile([bucket(realised=False, free=1, cap=2, hour=19)])
    assert profile == [{
        "dow": date(2026, 10, 1).isoweekday(), "hour": 19, "occupancy": 0.5, "court_hours": 2.0,
        "booking_value": 40.0, "avg_price": 40.0, "basis": "forward",
    }]


def test_booked_price_and_price_range():
    # Cheap hours fully booked, expensive hours empty: paid price sits below listed.
    buckets = [bucket(day=d, hour=10, free=0, cap=4, pph=20) for d in (1, 2, 3)] + [
        bucket(day=d, hour=19, free=4, cap=4, pph=60) for d in (1, 2, 3)
    ]
    stats = venue_stats(buckets, {"v1": 4})["v1"]
    assert stats.realised.booked_price == 20
    assert stats.prices.avg_price == 40
    assert (stats.prices.price_min, stats.prices.price_max) == (20, 60)


def test_hourly_profile_prefers_forward_until_a_week_of_history():
    few_days = [bucket(day=d, hour=18) for d in range(1, 4)] + [bucket(day=20, hour=19, realised=False)]
    assert {c["basis"] for c in hourly_profile(few_days)} == {"forward"}
    full_week = [bucket(day=d, hour=18) for d in range(1, 8)] + [bucket(day=20, hour=19, realised=False)]
    assert {c["basis"] for c in hourly_profile(full_week)} == {"realised"}
