"""Public location context for the site planner. No financial forecasts."""

import httpx

from sportscanner.insights import service
from sportscanner.insights.boroughs import borough_population
from sportscanner.insights.metrics import capacity, median_or_none, opportunity_score
from sportscanner.insights.demographics import radius_population


def catchment(sport, latitude, longitude, radius):
    market = service.market_report(sport)
    nearby = []
    for venue in market["venues"]:
        if venue["latitude"] is None or venue["longitude"] is None:
            continue
        distance = service._haversine_miles(
            latitude, longitude, venue["latitude"], venue["longitude"]
        )
        if distance <= radius:
            nearby.append({**venue, "distance_miles": round(distance, 2)})
    nearby.sort(key=lambda v: v["distance_miles"])
    demographics = radius_population(latitude, longitude, radius)
    courts = sum(v["courts"] or 0 for v in nearby)
    observed_courts = courts if any(v["courts"] is not None for v in nearby) else None
    population = demographics["population"]
    return {
        "sport": sport,
        "latitude": latitude,
        "longitude": longitude,
        "radius_miles": radius,
        "demographics": demographics,
        "venues": nearby,
        "summary": {
            "venues": len(nearby),
            "courts": courts,
            "median_price": median_or_none(v["avg_price_per_hour"] for v in nearby),
            "median_occupancy": median_or_none(v["occupancy"] for v in nearby),
            "measured_venues": sum(v["measured"] for v in nearby),
        },
        "opportunity": opportunity_score(
            courts_per_100k=(
                observed_courts / population * 100_000
                if observed_courts is not None and population
                else None
            ),
            forward_booked=median_or_none(v["forward_booked"] for v in nearby),
            occupancy=median_or_none(v["occupancy"] for v in nearby),
            avg_price_per_hour=median_or_none(v["avg_price_per_hour"] for v in nearby),
            reference_price_per_hour=market["summary"].get("median_price_per_hour"),
            basis=f"{radius:g} miles",
        ),
        "capacity": capacity(observed_courts, population),
        "boroughs": [
            {"name": name, **borough_population()["boroughs"][name]}
            for name in sorted(
                {
                    v["borough"]
                    for v in nearby
                    if v["borough"] in borough_population()["boroughs"]
                }
            )
        ],
    }


def constraints(latitude, longitude):
    # Government Planning Data API uses spatial intersection at the selected
    # point. A missing record is not proof the parcel is unconstrained.
    def build():
        response = httpx.get(
            "https://www.planning.data.gov.uk/entity.json",
            params=[
                ("latitude", latitude),
                ("longitude", longitude),
                ("limit", 100),
                ("dataset", "green-belt"),
                ("dataset", "flood-risk-zone"),
                ("dataset", "conservation-area"),
                ("dataset", "article-4-direction-area"),
                ("field", "name"),
                ("field", "dataset"),
                ("field", "reference"),
                ("field", "entity"),
            ],
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        return {
            "entities": payload.get("entities", []),
            "source": "https://www.planning.data.gov.uk/",
            "latitude": latitude,
            "longitude": longitude,
            "coverage": "England",
        }

    return service._cached(f"constraints:{latitude:.5f}:{longitude:.5f}", build)
