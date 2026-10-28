"""London radius populations using ONS LSOA population-weighted centroids.

Age and income come from separate ONS small-area releases bundled alongside the
population reference. Median age is the population-weighted mean of LSOA medians
(mid-2022). Income is the population-weighted mean of MSOA modelled means
(financial year ending 2023). ONS publishes modelled mean household income at
small-area level, not a median, so median_income is left null rather than
invented; mean_income carries the sourced figure.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional, Tuple

from sportscanner.insights.service import _haversine_miles

_DATA_DIR = Path(__file__).parent / "data"


@lru_cache(maxsize=1)
def reference():
    return json.loads((_DATA_DIR / "london_lsoa_population.json").read_text())


@lru_cache(maxsize=1)
def demographic_reference():
    return json.loads((_DATA_DIR / "london_lsoa_demographics.json").read_text())


@lru_cache(maxsize=1)
def _demographic_by_code():
    return {area["code"]: area for area in demographic_reference()["areas"]}


def _population_weighted_mean(values: Iterable[Tuple[float, Optional[float]]]) -> Optional[float]:
    present = [(weight, value) for weight, value in values if weight and value is not None]
    total = sum(weight for weight, _ in present)
    return sum(weight * value for weight, value in present) / total if total else None


def radius_population(latitude, longitude, radius):
    data = reference()
    age_income = _demographic_by_code()
    areas = [area for area in data["areas"]
             if _haversine_miles(latitude, longitude, area["latitude"], area["longitude"]) <= radius]
    groups = [("age_0_15", "0–15"), ("age_16_24", "16–24"), ("age_25_49", "25–49"),
              ("age_50_64", "50–64"), ("age_65_plus", "65+")]
    median_age = _population_weighted_mean(
        (area["population"], age_income.get(area["code"], {}).get("median_age")) for area in areas
    )
    mean_income = _population_weighted_mean(
        (area["population"], age_income.get(area["code"], {}).get("mean_income")) for area in areas
    )
    age_meta = demographic_reference()["median_age"]
    income_meta = demographic_reference()["income"]
    return {
        "year": data["year"], "population": sum(a["population"] for a in areas),
        "age_groups": [{"label": label, "population": sum(a[field] for a in areas)} for field, label in groups],
        "median_age": round(median_age, 1) if median_age is not None else None,
        "median_age_year": age_meta["year"],
        "median_age_source": age_meta["source"],
        "median_age_source_url": age_meta["source_url"],
        "median_age_licence": age_meta["licence"],
        "median_income": None,
        "mean_income": round(mean_income) if mean_income is not None else None,
        "income_year": income_meta["year"],
        "income_period": income_meta["period"],
        "income_measure": income_meta["measure"],
        "income_definition": income_meta["definition"],
        "income_source": income_meta["source"],
        "income_source_url": income_meta["source_url"],
        "income_licence": income_meta["licence"],
        "income_note": "ONS publishes modelled mean household income at small-area level, not a median; median_income is null rather than estimated.",
        "small_areas": len(areas), "source": data["source"], "licence": data["licence"],
        "coverage": "London residents only; whole LSOAs counted when their population-weighted centroid lies inside the radius.",
        "areas": [{"name": a["name"], "latitude": a["latitude"], "longitude": a["longitude"], "population": a["population"]} for a in areas],
    }
