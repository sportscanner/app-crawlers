import pytest

from sportscanner.insights.metrics import (
    OPPORTUNITY_WEIGHTS,
    capacity,
    opportunity_score,
)


def score(**overrides):
    values = dict(
        courts_per_100k=2.5,
        forward_booked=0.6,
        occupancy=0.35,
        avg_price_per_hour=40.0,
        reference_price_per_hour=80.0,
        basis="London · 3 miles",
    )
    values.update(overrides)
    return opportunity_score(**values)


def test_opportunity_weights_sum_to_one():
    assert sum(OPPORTUNITY_WEIGHTS.values()) == pytest.approx(1.0)
    assert set(OPPORTUNITY_WEIGHTS) == {"supply_gap", "demand", "occupancy", "pricing"}


def test_opportunity_components_and_weighted_score():
    result = score()
    components = {c["key"]: c for c in result["components"]}

    assert result["score"] == 64
    assert result["basis"] == "London · 3 miles"
    assert components["supply_gap"]["score"] == 75
    assert components["demand"]["score"] == 60
    assert components["occupancy"]["score"] == 65
    assert components["pricing"]["score"] == 50
    assert [c["weight"] for c in result["components"]] == list(OPPORTUNITY_WEIGHTS.values())
    assert all(0 <= c["score"] <= 100 for c in result["components"])


def test_opportunity_scores_are_clamped():
    low = score(courts_per_100k=25, forward_booked=0, occupancy=2, avg_price_per_hour=200)
    high = score(courts_per_100k=-5, forward_booked=2, occupancy=-1, avg_price_per_hour=0)
    low_components = {c["key"]: c["score"] for c in low["components"]}
    high_components = {c["key"]: c["score"] for c in high["components"]}

    assert low_components == {"supply_gap": 0, "demand": 0, "occupancy": 0, "pricing": 0}
    assert high_components == {"supply_gap": 100, "demand": 100, "occupancy": 100, "pricing": 100}


def test_opportunity_is_null_when_an_input_is_missing():
    result = score(occupancy=None)
    assert result["score"] is None
    assert result["components"] == []
    assert "occupancy" in result["reason"]


def test_opportunity_is_null_without_a_price_reference():
    result = score(reference_price_per_hour=None)
    assert result["score"] is None
    assert result["components"] == []
    assert "median price" in result["reason"]


def test_capacity_matches_the_one_court_per_10000_target():
    result = capacity(102, 3_570_000)
    assert result == {
        "courts": 102,
        "target_courts": 357,
        "headroom_courts": 255,
        "saturation_pct": 28.6,
        "target_basis": "1 court per 10,000 people",
    }


def test_capacity_headroom_goes_negative_above_target():
    result = capacity(400, 3_570_000)
    assert result["headroom_courts"] == -43
    assert result["saturation_pct"] == 112.0


def test_capacity_is_null_without_population():
    result = capacity(102, None)
    assert result["courts"] == 102
    assert result["target_courts"] is None
    assert result["headroom_courts"] is None
    assert result["saturation_pct"] is None


def test_capacity_without_known_courts_keeps_the_target():
    result = capacity(None, 3_570_000)
    assert result["courts"] is None
    assert result["target_courts"] == 357
    assert result["headroom_courts"] is None
    assert result["saturation_pct"] is None
