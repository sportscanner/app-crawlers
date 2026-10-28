"""Pure metric definitions over hourly slot buckets.

A bucket is one venue's courts for one clock hour on one date: how many court
units were offered (`cap`), how many were still free at the last observation
before start (`free`) and the listed price per court-hour (`pph`). Everything
here is plain Python so the definitions can be tested without a database.

Definitions (kept in step with the methodology copy on the frontend):
- Occupancy = booked court-hours / offered court-hours, booked = cap - free.
- Estimated booking value = booked court-hours x listed price per hour. Court
  hire only, at listed prices, before any discounts. It is not revenue.
- Peak = weekdays 07:00-09:00 and 17:00-22:00 plus all weekend hours, matching
  the convention other UK court market reports use so figures compare.

Opportunity score (0-100) is a heuristic for comparing areas, not a forecast.
Four components are scored 0-100 and combined with fixed weights:
- supply_gap (0.35) = 100 x (1 - courts per 100k / 10), clamped to 0-100.
- demand (0.25) = 100 x share of the next 7 days already booked, clamped.
- occupancy (0.20) = 100 x (1 - occupancy), clamped. More spare capacity scores higher.
- pricing (0.20) = 100 x (1 - area price / London median price), clamped.
The score is the weighted mean, rounded to an integer. It is null with an empty
component list and a reason when any input, or the price reference, is missing.
Higher means more apparent scope for courts, demand or price headroom; it says
nothing about profitability.

Capacity compares observed public courts with a target of one court per 10,000
people (10 per 100k). Headroom is negative when observed supply exceeds target.
"""

from dataclasses import dataclass, field
from datetime import date
from statistics import mean, median
from typing import Dict, Iterable, List, Optional

# Below this many offered court-hours, or this many distinct days, a venue's
# occupancy is too noisy to show (one busy evening is not a trend).
MIN_COURT_HOURS_FOR_OCCUPANCY = 20
MIN_DAYS_FOR_OCCUPANCY = 3
# The weekday x hour profile needs every weekday represented before realised
# history replaces the forward book.
MIN_DAYS_FOR_REALISED_PROFILE = 7
MIN_PRICED_SHARE_FOR_VALUE = 0.8
RUN_RATE_DAYS = 28
_WEEKDAY_PEAK_HOURS = frozenset({7, 8, 17, 18, 19, 20, 21})

TARGET_COURTS_PER_100K = 10.0
COURTS_PER_PERSON_TARGET = 10_000
CAPACITY_TARGET_BASIS = "1 court per 10,000 people"
OPPORTUNITY_WEIGHTS = {
    "supply_gap": 0.35,
    "demand": 0.25,
    "occupancy": 0.20,
    "pricing": 0.20,
}
METRIC_DEFINITIONS = {
    "gbv": {
        "label": "Gross booking value",
        "definition": "Court hire at listed prices, including VAT, before platform commission.",
    },
    "occupancy": {
        "label": "Occupancy",
        "definition": "Share of offered court-hours that are booked.",
    },
    "revpah": {
        "label": "RevPAH",
        "definition": "Gross booking value per available court-hour.",
    },
    "gbv_per_court": {
        "label": "GBV per court",
        "definition": "Monthly gross booking value divided by courts.",
    },
    "courts_per_100k": {
        "label": "Courts per 100k",
        "definition": "Public courts per 100,000 residents.",
    },
}


@dataclass(frozen=True)
class Bucket:
    composite_key: str
    day: date
    dow: int  # ISO weekday, Monday = 1
    hour: int
    realised: bool  # True once the hour has started; False for forward bookings
    free: float
    cap: float
    pph: Optional[float]
    indoor: Optional[bool]

    @property
    def booked(self) -> float:
        return max(self.cap - self.free, 0.0)


def is_peak(dow: int, hour: int) -> bool:
    return dow >= 6 or hour in _WEEKDAY_PEAK_HOURS


def _ratio(numerator: float, denominator: float) -> Optional[float]:
    return numerator / denominator if denominator > 0 else None


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def capacity(courts: Optional[float], population: Optional[int]) -> dict:
    """Observed public courts against a population-based target.

    Target = population / 10,000, which is 10 courts per 100,000 people.
    Population-unknown responses leave the target, headroom and saturation null.
    """
    observed = int(round(courts)) if courts is not None else None
    if not population or population <= 0:
        return {
            "courts": observed,
            "target_courts": None,
            "headroom_courts": None,
            "saturation_pct": None,
            "target_basis": CAPACITY_TARGET_BASIS,
        }
    target = population / COURTS_PER_PERSON_TARGET
    target_courts = int(round(target))
    return {
        "courts": observed,
        "target_courts": target_courts,
        "headroom_courts": target_courts - observed if observed is not None else None,
        "saturation_pct": round(observed / target * 100, 1) if observed is not None and target > 0 else None,
        "target_basis": CAPACITY_TARGET_BASIS,
    }


def opportunity_score(
    *,
    courts_per_100k: Optional[float],
    forward_booked: Optional[float],
    occupancy: Optional[float],
    avg_price_per_hour: Optional[float],
    reference_price_per_hour: Optional[float],
    basis: str,
) -> dict:
    """Explainable 0-100 opportunity heuristic for comparing areas.

    Every input is a plain number from the report already being built; no
    extra data is loaded. See the module docstring for the formula. Missing
    inputs return a null score, no components and a reason instead of a
    partial score that would look more certain than the data supports.
    """
    missing = []
    if courts_per_100k is None:
        missing.append("courts per 100k")
    if forward_booked is None:
        missing.append("forward bookings")
    if occupancy is None:
        missing.append("occupancy")
    if avg_price_per_hour is None:
        missing.append("price per hour")
    if reference_price_per_hour is None or reference_price_per_hour <= 0:
        missing.append("a London median price")
    if missing:
        return {
            "score": None,
            "basis": basis,
            "components": [],
            "reason": f"Not enough data for {', '.join(missing)}.",
        }

    raw = {
        "supply_gap": _clamp_score(100 * (1 - courts_per_100k / TARGET_COURTS_PER_100K)),
        "demand": _clamp_score(100 * forward_booked),
        "occupancy": _clamp_score(100 * (1 - occupancy)),
        "pricing": _clamp_score(100 * (1 - avg_price_per_hour / reference_price_per_hour)),
    }
    details = {
        "supply_gap": f"{courts_per_100k:.1f} courts per 100k vs a {TARGET_COURTS_PER_100K:.0f} per 100k target",
        "demand": f"{forward_booked:.0%} of the next 7 days already booked",
        "occupancy": f"{occupancy:.0%} of realised court-hours booked",
        "pricing": f"£{avg_price_per_hour:.2f}/hr vs a London median of £{reference_price_per_hour:.2f}/hr",
    }
    labels = {
        "supply_gap": "Supply gap",
        "demand": "Demand",
        "occupancy": "Occupancy headroom",
        "pricing": "Price headroom",
    }
    components = [
        {
            "key": key,
            "label": labels[key],
            "score": int(round(raw[key])),
            "weight": weight,
            "detail": details[key],
        }
        for key, weight in OPPORTUNITY_WEIGHTS.items()
    ]
    score = int(round(sum(raw[key] * weight for key, weight in OPPORTUNITY_WEIGHTS.items())))
    return {"score": score, "basis": basis, "components": components}


@dataclass
class Tally:
    """Running sums for one group of buckets (a venue, a borough, an hour...)."""

    offered: float = 0.0
    booked: float = 0.0
    value: float = 0.0
    priced_offered: float = 0.0
    priced_booked: float = 0.0
    price_weighted: float = 0.0
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    days: set = field(default_factory=set)

    def add(self, b: Bucket) -> None:
        self.offered += b.cap
        self.booked += b.booked
        self.days.add(b.day)
        if b.pph is not None:
            self.value += b.booked * b.pph
            self.priced_offered += b.cap
            self.priced_booked += b.booked
            self.price_weighted += b.cap * b.pph
            self.price_min = b.pph if self.price_min is None else min(self.price_min, b.pph)
            self.price_max = b.pph if self.price_max is None else max(self.price_max, b.pph)

    @property
    def measurable(self) -> bool:
        return self.offered >= MIN_COURT_HOURS_FOR_OCCUPANCY and len(self.days) >= MIN_DAYS_FOR_OCCUPANCY

    @property
    def occupancy(self) -> Optional[float]:
        return _ratio(self.booked, self.offered) if self.measurable else None

    @property
    def booked_price(self) -> Optional[float]:
        """Average listed price of the court-hours that were actually booked. Below
        the listed average when bookings lean to cheaper (off-peak) hours."""
        return _ratio(self.value, self.priced_booked) if self.measurable else None

    @property
    def avg_price(self) -> Optional[float]:
        """Listed price per court-hour, weighted by the hours each price applies to."""
        return _ratio(self.price_weighted, self.priced_offered)

    @property
    def monthly_value(self) -> Optional[float]:
        """28-day run-rate of estimated booking value over the days observed."""
        if not self.measurable or self.priced_offered < self.offered * MIN_PRICED_SHARE_FOR_VALUE:
            return None
        return self.value / len(self.days) * RUN_RATE_DAYS

    @property
    def revpah(self) -> Optional[float]:
        """Estimated booking value per offered court-hour."""
        return _ratio(self.value, self.offered) if self.monthly_value is not None else None


@dataclass
class VenueStats:
    composite_key: str
    courts: int
    realised: Tally = field(default_factory=Tally)
    realised_peak: Tally = field(default_factory=Tally)
    realised_offpeak: Tally = field(default_factory=Tally)
    forward: Tally = field(default_factory=Tally)
    # Listed prices across every observed hour, past and upcoming.
    prices: Tally = field(default_factory=Tally)
    prices_peak: Tally = field(default_factory=Tally)
    prices_offpeak: Tally = field(default_factory=Tally)
    indoor_votes: List[bool] = field(default_factory=list)

    @property
    def indoor(self) -> Optional[bool]:
        if not self.indoor_votes:
            return None
        return sum(self.indoor_votes) * 2 >= len(self.indoor_votes)


def venue_stats(buckets: Iterable[Bucket], courts: Dict[str, int]) -> Dict[str, VenueStats]:
    stats: Dict[str, VenueStats] = {}
    for b in buckets:
        s = stats.get(b.composite_key)
        if s is None:
            s = stats[b.composite_key] = VenueStats(b.composite_key, courts.get(b.composite_key, 0))
        peak = is_peak(b.dow, b.hour)
        if b.realised:
            s.realised.add(b)
            (s.realised_peak if peak else s.realised_offpeak).add(b)
        else:
            s.forward.add(b)
        s.prices.add(b)
        (s.prices_peak if peak else s.prices_offpeak).add(b)
        if b.indoor is not None:
            s.indoor_votes.append(b.indoor)
    return stats


def hourly_profile(buckets: Iterable[Bucket]) -> List[dict]:
    """Occupancy by weekday x hour. Uses realised hours once they cover a full
    week, and the forward book (bookings already made for the next 7 days)
    before that, e.g. in the first days after history collection starts."""
    realised: Dict[tuple, Tally] = {}
    forward: Dict[tuple, Tally] = {}
    realised_days = set()
    for b in buckets:
        (realised if b.realised else forward).setdefault((b.dow, b.hour), Tally()).add(b)
        if b.realised:
            realised_days.add(b.day)
    source = realised if len(realised_days) >= MIN_DAYS_FOR_REALISED_PROFILE or not forward else forward
    return [
        {
            "dow": dow,
            "hour": hour,
            "occupancy": _ratio(t.booked, t.offered),
            "court_hours": round(t.offered, 1),
            # Average booked value per occurrence of this weekday-hour, for the value heatmap.
            "booking_value": round(t.value / len(t.days), 2) if t.days else None,
            "avg_price": round(t.avg_price, 2) if t.avg_price is not None else None,
            "basis": "realised" if source is realised else "forward",
        }
        for (dow, hour), t in sorted(source.items())
    ]


def median_or_none(values: Iterable[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return median(present) if present else None


def mean_or_none(values: Iterable[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return mean(present) if present else None
