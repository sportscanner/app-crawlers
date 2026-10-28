from sportscanner.insights.demographics import demographic_reference, radius_population, reference


def test_official_reference_has_complete_age_bands_and_centroids():
    data = reference()
    assert data["year"] == 2024
    assert len(data["areas"]) == 4994
    assert sum(a["population"] for a in data["areas"]) == 9089736
    for area in data["areas"]:
        assert -0.65 <= area["longitude"] <= 0.35
        assert 51.25 <= area["latitude"] <= 51.75
        assert area["population"] == sum(area[k] for k in ("age_0_15", "age_16_24", "age_25_49", "age_50_64", "age_65_plus"))


def test_demographic_reference_covers_every_population_area():
    areas = {area["code"]: area for area in demographic_reference()["areas"]}
    assert len(areas) == 4994
    for area in reference()["areas"]:
        assert 0 < areas[area["code"]]["median_age"] < 100
        assert areas[area["code"]]["mean_income"] > 0
    assert demographic_reference()["income"]["measure"] == "mean"


def test_radius_counts_london_centroids_and_preserves_age_totals():
    report = radius_population(51.5074, -0.1278, 3)
    assert report["small_areas"] > 0
    assert report["population"] == sum(g["population"] for g in report["age_groups"])
    assert radius_population(53, -3, 3)["population"] == 0


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
    assert radius_population(53, -3, 3)["median_age"] is None
