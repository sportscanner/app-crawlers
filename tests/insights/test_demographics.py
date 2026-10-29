from sportscanner.insights.demographics import (
    demographic_reference,
    london_summary,
    radius_population,
    reference,
)

# Edinburgh is outside the England and Wales small-area reference.
OUTSIDE = (55.9533, -3.1883)
MANCHESTER = (53.4808, -2.2426)


def test_official_reference_has_complete_age_bands_and_centroids():
    data = reference()
    assert data["year"] == 2024
    assert len(data["areas"]) == 35672
    assert sum(a["population"] for a in data["areas"]) == 61806682
    assert len(data["london_codes"]) == 4994
    for area in data["areas"]:
        assert -8 <= area["longitude"] <= 2
        assert 49 <= area["latitude"] <= 61
        assert area["population"] == sum(
            area[k]
            for k in ("age_0_15", "age_16_24", "age_25_49", "age_50_64", "age_65_plus")
        )


def test_demographic_reference_covers_every_population_area():
    areas = {area["code"]: area for area in demographic_reference()["areas"]}
    assert len(areas) == 35672
    for area in reference()["areas"]:
        assert 0 < areas[area["code"]]["median_age"] < 100
    assert any(area["mean_income"] is not None for area in areas.values())
    assert demographic_reference()["income"]["measure"] == "mean"


def test_radius_counts_small_areas_and_preserves_age_totals():
    report = radius_population(51.5074, -0.1278, 3)
    assert report["small_areas"] > 0
    assert report["population"] == sum(g["population"] for g in report["age_groups"])
    assert radius_population(*MANCHESTER, 3)["population"] > 0
    assert radius_population(*OUTSIDE, 3)["population"] == 0


def test_radius_includes_sourced_age_and_income_fields():
    report = radius_population(51.5074, -0.1278, 3)
    assert 20 < report["median_age"] < 55
    assert report["median_age_year"] == 2022
    assert "ONS" in report["median_age_source"]
    assert report["median_income"] is None
    assert report["mean_income"] > 0
    assert report["income_year"] == "2023"
    assert report["income_measure"] == "mean"
    assert "ONS" in report["income_source"]
    assert "median" in report["income_note"]
    assert radius_population(*MANCHESTER, 3)["median_age"] > 0
    assert radius_population(*OUTSIDE, 3)["median_age"] is None


def test_english_areas_have_a_deprivation_decile():
    assert demographic_reference()["deprivation"]["year"] == 2025
    for area in demographic_reference()["areas"]:
        if area["code"].startswith("E"):
            assert 1 <= area["imd_decile"] <= 10
        else:
            assert area["imd_decile"] is None


def test_radius_reports_deprivation_income_bands_and_london_baseline():
    report = radius_population(51.5074, -0.1278, 3)
    deciles = report["deprivation"]["deciles"]
    assert [d["decile"] for d in deciles] == list(range(1, 11))
    assert sum(d["population"] for d in deciles) == report["population"]
    assert sum(b["population"] for b in report["income_bands"]) == report["population"]
    assert 0 <= report["deprivation"]["least_deprived_20_share"] <= 1
    assert "Indices of Deprivation 2025" in report["deprivation"]["source"]
    london = report["london"]
    assert london["population"] == 9089736
    assert london == london_summary()
    assert sum(g["population"] for g in london["age_groups"]) == london["population"]
    assert all("imd_decile" in a and "mean_income" in a for a in report["areas"])
    assert report["coverage_areas"] == ["England", "Wales"]
    empty = radius_population(*OUTSIDE, 3)
    assert empty["deprivation"]["least_deprived_20_share"] is None
    assert empty["coverage_areas"] == ["England", "Wales"]
