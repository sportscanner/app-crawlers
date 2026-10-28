from datetime import date, time

import pytest

from sportscanner.insights.history import price_history, summarise_price_pairs


def quote(day, price, venue="a", hour=17, duration=60, dow=1):
    return dict(observed_on=date(2026, 10, day), price_per_hour=price,
                composite_key=venue, dow=dow, starting_time=time(hour), duration_min=duration)


def test_new_expensive_venue_does_not_cause_price_inflation():
    report = price_history([quote(1, 10), quote(2, 10), quote(2, 100, "new")])
    assert report["change_percent"] == 0
    assert report["series"][-1]["matched_venues"] == 1


def test_matching_keeps_duration_weekday_and_start_time_separate():
    report = price_history([quote(1, 10), quote(2, 20, duration=40), quote(2, 20, dow=2), quote(2, 20, hour=18)])
    assert report["change_percent"] is None
    assert report["series"][-1]["index"] is None


def test_venue_weighting_does_not_give_large_schedules_more_influence():
    rows = [quote(1, 10, "small"), quote(2, 20, "small")]
    for hour in range(8, 20):
        rows += [quote(1, 20, "large", hour), quote(2, 20, "large", hour)]
    report = price_history(rows)
    assert report["change_percent"] == 50
    assert report["series"][-1]["matched_samples"] == 13


def test_missing_days_are_null_not_interpolated():
    report = price_history([quote(1, 10), quote(3, 11)])
    assert report["observed_days"] == 2
    assert report["series"][1]["index"] is None
    assert report["change_percent"] == 10


def test_free_prices_stored_without_dividing_by_zero():
    report = price_history([quote(1, 0), quote(2, 5)])
    assert report["change_percent"] is None
    assert report["venues"][0]["before"] == 0


def test_no_historical_points_invented_for_new_collection():
    assert price_history([])["series"] == []
    report = price_history([quote(1, 10)])
    assert len(report["series"]) == 1
    assert report["change_percent"] is None


def test_aggregated_pairs_keep_equal_venue_weights_and_calendar_gaps():
    bounds = {"first_day": date(2026, 10, 1), "last_day": date(2026, 10, 3), "observed_days": 2}
    pairs = [{"observed_on": date(2026, 10, day), "composite_key": venue,
              "ratio": ratio if day == 3 else 1, "ratio_samples": samples, "matched_samples": samples,
              "before": 10, "after": 10 * (ratio if day == 3 else 1)}
             for day in (1, 3) for venue, ratio, samples in [("a", 2, 1), ("b", 1, 50)]]
    report = summarise_price_pairs(bounds, pairs)
    assert report["change_percent"] == 50
    assert report["series"][1]["index"] is None
    assert report["series"][-1]["matched_samples"] == 51


@pytest.mark.parametrize("sport", ["badminton", "squash", "pickleball", "padel", "tennis"])
def test_court_parser_supports_all_sports(sport):
    from sportscanner.insights.planning import PLANNING_TOPICS, courts_proposed
    assert sport in PLANNING_TOPICS
    assert courts_proposed(f"two new {sport} courts", sport) == 2
