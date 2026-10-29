"""England and Wales radius populations using ONS LSOA population-weighted centroids.

Age and income come from separate ONS small-area releases bundled alongside the
population reference. Median age is the population-weighted mean of LSOA medians
(mid-2022). Income is the population-weighted mean of MSOA modelled means
(financial year ending 2023). ONS publishes modelled mean household income at
small-area level, not a median, so median_income is left null rather than
invented; mean_income carries the sourced figure.

Deprivation is the English Indices of Deprivation 2025 IMD decile of each LSOA
(1 = most deprived 10% in England), summed as residents per decile. Welsh LSOAs
have no IMD decile in this release, so their residents are left out of the
deprivation shares rather than treated as least deprived. Income bands count
residents by their MSOA's modelled mean, so they describe areas, not individual
households. Every report carries the same figures for all of London so the
catchment can be compared with it.

Coverage is England and Wales, the geography the ONS small-area releases cover.
Scotland and Northern Ireland use different small-area geographies and are not
included; the report says so rather than returning a silent zero.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional, Tuple

from sportscanner.insights.service import _haversine_miles

_DATA_DIR = Path(__file__).parent / "data"


@lru_cache(maxsize=1)
def reference():
    return json.loads((_DATA_DIR / "ew_lsoa_population.json").read_text())


@lru_cache(maxsize=1)
def demographic_reference():
    return json.loads((_DATA_DIR / "ew_lsoa_demographics.json").read_text())


@lru_cache(maxsize=1)
def _demographic_by_code():
    return {area["code"]: area for area in demographic_reference()["areas"]}


def _population_weighted_mean(
    values: Iterable[Tuple[float, Optional[float]]],
) -> Optional[float]:
    present = [
        (weight, value) for weight, value in values if weight and value is not None
    ]
    total = sum(weight for weight, _ in present)
    return sum(weight * value for weight, value in present) / total if total else None


AGE_GROUPS = [
    ("age_0_15", "0–15"),
    ("age_16_24", "16–24"),
    ("age_25_49", "25–49"),
    ("age_50_64", "50–64"),
    ("age_65_plus", "65+"),
]
# Bands of MSOA modelled mean equivalised disposable household income.
INCOME_BANDS = [
    (0, 40_000, "Under £40k"),
    (40_000, 45_000, "£40–45k"),
    (45_000, 50_000, "£45–50k"),
    (50_000, 60_000, "£50–60k"),
    (60_000, 70_000, "£60–70k"),
    (70_000, None, "£70k+"),
]


def _summarise(areas):
    """Population, age, income and deprivation figures for a set of LSOAs."""
    extra = _demographic_by_code()
    population = sum(a["population"] for a in areas)

    def weighted(field):
        return _population_weighted_mean(
            (a["population"], extra.get(a["code"], {}).get(field)) for a in areas
        )

    median_age = weighted("median_age")
    mean_income = weighted("mean_income")
    deciles = [0] * 10
    bands = [0] * len(INCOME_BANDS)
    for area in areas:
        info = extra.get(area["code"], {})
        if info.get("imd_decile"):
            deciles[info["imd_decile"] - 1] += area["population"]
        income = info.get("mean_income")
        if income is not None:
            for i, (low, high, _) in enumerate(INCOME_BANDS):
                if income >= low and (high is None or income < high):
                    bands[i] += area["population"]
                    break
    ranked = sum(deciles)
    return {
        "population": population,
        "age_groups": [
            {"label": label, "population": sum(a[field] for a in areas)}
            for field, label in AGE_GROUPS
        ],
        "median_age": round(median_age, 1) if median_age is not None else None,
        "mean_income": round(mean_income) if mean_income is not None else None,
        "deprivation": {
            "deciles": [
                {"decile": i + 1, "population": n} for i, n in enumerate(deciles)
            ],
            "most_deprived_20_share": (
                round((deciles[0] + deciles[1]) / ranked, 4) if ranked else None
            ),
            "least_deprived_20_share": (
                round((deciles[8] + deciles[9]) / ranked, 4) if ranked else None
            ),
        },
        "income_bands": [
            {"label": label, "population": bands[i]}
            for i, (_, _, label) in enumerate(INCOME_BANDS)
        ],
    }


@lru_cache(maxsize=1)
def _london_codes():
    return set(reference().get("london_codes") or ())


@lru_cache(maxsize=1)
def london_summary():
    codes = _london_codes()
    return _summarise([area for area in reference()["areas"] if area["code"] in codes])


def radius_population(latitude, longitude, radius):
    data = reference()
    extra = _demographic_by_code()
    areas = [
        area
        for area in data["areas"]
        if _haversine_miles(latitude, longitude, area["latitude"], area["longitude"])
        <= radius
    ]
    summary = _summarise(areas)
    meta = demographic_reference()
    age_meta = meta["median_age"]
    income_meta = meta["income"]
    deprivation_meta = meta.get("deprivation", {})
    return {
        "year": data["year"],
        "population": summary["population"],
        "age_groups": summary["age_groups"],
        "median_age": summary["median_age"],
        "median_age_year": age_meta["year"],
        "median_age_source": age_meta["source"],
        "median_age_source_url": age_meta["source_url"],
        "median_age_licence": age_meta["licence"],
        "median_income": None,
        "mean_income": summary["mean_income"],
        "income_year": income_meta["year"],
        "income_period": income_meta["period"],
        "income_measure": income_meta["measure"],
        "income_definition": income_meta["definition"],
        "income_source": income_meta["source"],
        "income_source_url": income_meta["source_url"],
        "income_licence": income_meta["licence"],
        "income_note": "ONS publishes modelled mean household income at small-area level, not a median; median_income is null rather than estimated.",
        "income_bands": summary["income_bands"],
        "deprivation": {**summary["deprivation"], **deprivation_meta},
        "london": london_summary(),
        "small_areas": len(areas),
        "source": data["source"],
        "licence": data["licence"],
        "coverage": (
            "England and Wales residents only; whole LSOAs counted when their "
            "population-weighted centroid lies inside the radius. Scotland and "
            "Northern Ireland use different small-area geographies and are not covered."
        ),
        "coverage_areas": ["England", "Wales"],
        "deprivation_coverage": "England",
        "areas": [
            {
                "name": a["name"],
                "latitude": a["latitude"],
                "longitude": a["longitude"],
                "population": a["population"],
                "mean_income": extra.get(a["code"], {}).get("mean_income"),
                "imd_decile": extra.get(a["code"], {}).get("imd_decile"),
            }
            for a in areas
        ],
    }
