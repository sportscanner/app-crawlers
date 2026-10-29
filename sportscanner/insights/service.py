"""Builds the market and venue insight reports from `slot_history`.

The database does the heavy lifting (one pass bucketing slots into venue-hours);
everything after that is the pure metric code in `metrics.py`. Reports are
cached in-process for a few minutes: the history only changes once per 15-minute
crawl, and the market report scans up to 35 days of slots.
"""

import math
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
from threading import RLock

from sqlalchemy import text

import sportscanner.storage.postgres.database as db
from sportscanner.insights.boroughs import (
    OUTSIDE_LONDON,
    borough_population,
    london_population,
    resolve_boroughs,
    borough_name,
)
from sportscanner.insights.history import summarise_price_pairs
from sportscanner.insights.planning import applications_within
from sportscanner.insights.metrics import (
    Bucket,
    METRIC_DEFINITIONS,
    RUN_RATE_DAYS,
    Tally,
    VenueStats,
    capacity,
    hourly_profile,
    mean_or_none,
    median_or_none,
    opportunity_score,
    venue_stats,
)

REALISED_WINDOW_DAYS = 28
# Yearly run-rate = 28-day run-rate scaled to a year. Not seasonally adjusted.
YEAR_DAYS = 365
FORWARD_WINDOW_DAYS = 7
NEARBY_RADIUS_MILES = 3.0
# A realised slot only counts if we saw it this close to its start time; older
# observations would miss late bookings and cancellations.
_MAX_STALENESS_BEFORE_START = timedelta(minutes=90)
_FORWARD_FRESHNESS = timedelta(hours=3)
_CACHE_TTL_SECONDS = 10 * 60

_SPORTS = ("badminton", "squash", "pickleball", "padel", "tennis")
# Sports played indoors by definition; their tables carry no indoor column.
_ALWAYS_INDOOR = ("badminton", "squash")

_cache: Dict[str, Tuple[float, dict]] = {}
_cache_lock = RLock()


def _now_london() -> datetime:
    return datetime.now(ZoneInfo("Europe/London")).replace(tzinfo=None)


def _cached(key: str, build):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL_SECONDS:
            return hit[1]
    value = build()
    with _cache_lock:
        if len(_cache) >= 256:
            expired = [
                k
                for k, (created, _) in _cache.items()
                if time.time() - created >= _CACHE_TTL_SECONDS
            ]
            for stale in expired:
                _cache.pop(stale, None)
            if len(_cache) >= 256:
                _cache.pop(min(_cache, key=lambda k: _cache[k][0]), None)
        _cache[key] = (time.time(), value)
    return value


def _rows(sql: str, **params) -> list:
    with db.engine.connect() as conn:
        return conn.execute(text(sql), params).mappings().all()


def _history_exists() -> bool:
    return bool(
        _rows("SELECT to_regclass('public.slot_history') IS NOT NULL AS ok")[0]["ok"]
    )


def _load_buckets(
    sport: str, now: datetime, composite_key: Optional[str] = None
) -> Tuple[List[Bucket], Dict[str, int]]:
    window_start = now - timedelta(days=REALISED_WINDOW_DAYS)
    forward_end = now + timedelta(days=FORWARD_WINDOW_DAYS)
    venue_filter = "AND h.composite_key = :composite_key" if composite_key else ""
    rows = _rows(
        f"""
        WITH courts AS (
            SELECT composite_key, GREATEST(MAX(max_spaces), 1) AS courts
            FROM public.slot_history h
            WHERE sport = :sport AND starts_at >= :window_start AND starts_at < :forward_end {venue_filter}
            GROUP BY composite_key
        ),
        slots AS (
            SELECT
                h.composite_key,
                h.starts_at,
                COALESCE(h.capacity, c.courts) AS cap,
                LEAST(GREATEST(h.last_spaces, 0), COALESCE(h.capacity, c.courts)) AS free,
                CASE WHEN h.price_gbp >= 0 AND h.duration_min > 0
                     THEN h.price_gbp * 60.0 / h.duration_min END AS pph,
                h.indoor
            FROM public.slot_history h
            JOIN courts c USING (composite_key)
            WHERE h.sport = :sport
              AND h.starts_at >= :window_start AND h.starts_at < :forward_end
              {venue_filter}
              AND CASE WHEN h.starts_at <= :now
                       THEN h.last_seen >= h.starts_at - :staleness
                       ELSE h.last_seen >= :now - :freshness END
        )
        SELECT
            composite_key,
            starts_at::date AS day,
            EXTRACT(ISODOW FROM starts_at)::int AS dow,
            EXTRACT(HOUR FROM starts_at)::int AS hour,
            MIN(starts_at) <= :now AS realised,
            -- Several slots can start in one hour (60/90-minute variants, on-the-hour and
            -- half-past starts); average them into one court-hour estimate.
            AVG(free)::float AS free,
            MAX(cap)::float AS cap,
            AVG(pph)::float AS pph,
            BOOL_OR(indoor) AS indoor
        FROM slots
        GROUP BY composite_key, day, dow, hour
        """,
        sport=sport,
        now=now,
        window_start=window_start,
        forward_end=forward_end,
        staleness=_MAX_STALENESS_BEFORE_START,
        freshness=_FORWARD_FRESHNESS,
        **({"composite_key": composite_key} if composite_key else {}),
    )
    buckets: List[Bucket] = []
    courts: Dict[str, int] = {}
    for r in rows:
        indoor = True if sport in _ALWAYS_INDOOR else r["indoor"]
        buckets.append(
            Bucket(
                composite_key=r["composite_key"],
                day=r["day"],
                dow=r["dow"],
                hour=r["hour"],
                realised=r["realised"],
                free=r["free"],
                cap=r["cap"],
                pph=r["pph"],
                indoor=indoor,
            )
        )
        courts[r["composite_key"]] = max(
            courts.get(r["composite_key"], 0), int(r["cap"])
        )
    return buckets, courts


def _venues(sport: str) -> List[dict]:
    return [
        dict(r)
        for r in _rows(
            """
        SELECT composite_key, venue_name, organisation, organisation_website, postcode,
               address, latitude, longitude
        FROM public.sportsvenue
        WHERE sports @> ARRAY[:sport]::varchar[]
        """,
            sport=sport,
        )
    ]


def _coverage(sport: str, now: datetime) -> Dict[str, dict]:
    """Per-venue freshness: when we last saw any slot for it."""
    rows = _rows(
        """
        SELECT composite_key, MAX(last_seen) AS last_seen, MIN(first_seen) AS first_seen
        FROM public.slot_history
        WHERE sport = :sport AND starts_at >= :since
        GROUP BY composite_key
        """,
        sport=sport,
        since=now - timedelta(days=REALISED_WINDOW_DAYS),
    )
    return {r["composite_key"]: dict(r) for r in rows}


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _opportunity(
    *,
    basis: str,
    courts: Optional[int],
    population: Optional[int],
    forward_booked: Optional[float],
    occupancy: Optional[float],
    avg_price_per_hour: Optional[float],
    reference_price_per_hour: Optional[float],
) -> dict:
    return opportunity_score(
        courts_per_100k=(
            courts / population * 100_000 if courts is not None and population else None
        ),
        forward_booked=forward_booked,
        occupancy=occupancy,
        avg_price_per_hour=avg_price_per_hour,
        reference_price_per_hour=reference_price_per_hour,
        basis=basis,
    )


def _venue_row(
    venue: dict, stats: Optional[VenueStats], borough: Optional[str], sport: str
) -> dict:
    s = stats or VenueStats(venue["composite_key"], 0)
    indoor = True if sport in _ALWAYS_INDOOR else s.indoor
    monthly = s.realised.monthly_value
    per_court = monthly / s.courts if monthly is not None and s.courts else None
    return {
        "composite_key": venue["composite_key"],
        "venue_name": venue["venue_name"],
        "organisation": venue["organisation"],
        "borough": borough,
        "postcode": venue["postcode"],
        "address": venue.get("address"),
        "website": venue.get("organisation_website"),
        "latitude": venue["latitude"],
        "longitude": venue["longitude"],
        "courts": s.courts or None,
        "setting": None if indoor is None else ("indoor" if indoor else "outdoor"),
        "occupancy": _round(s.realised.occupancy, 4),
        "peak_occupancy": _round(s.realised_peak.occupancy, 4),
        "offpeak_occupancy": _round(s.realised_offpeak.occupancy, 4),
        "forward_booked": _round(s.forward.occupancy, 4),
        "avg_price_per_hour": _round(s.prices.avg_price),
        "peak_price_per_hour": _round(s.prices_peak.avg_price),
        "offpeak_price_per_hour": _round(s.prices_offpeak.avg_price),
        "min_price_per_hour": _round(s.prices.price_min),
        "max_price_per_hour": _round(s.prices.price_max),
        "avg_booked_price": _round(s.realised.booked_price),
        "est_monthly_value": _round(monthly, 0),
        "est_yearly_value": (
            _round(monthly * YEAR_DAYS / RUN_RATE_DAYS, 0)
            if monthly is not None
            else None
        ),
        "est_monthly_value_per_court": _round(per_court, 0),
        "gbv_per_court": _round(per_court, 0),
        "revpah": _round(s.realised.revpah),
        "observed_days": len(s.realised.days),
        "measured": s.realised.occupancy is not None,
    }


def _rank(rows: List[dict], field: str, key: str) -> Optional[int]:
    ranked = sorted(
        (r for r in rows if r[field] is not None), key=lambda r: r[field], reverse=True
    )
    for i, r in enumerate(ranked, start=1):
        if r["composite_key"] == key:
            return i
    return None


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(a))


def _summary(rows: List[dict], stats: Dict[str, VenueStats]) -> dict:
    # Market occupancy pools measured venues only, so a venue with a few hours
    # of history can't swing the London figure.
    realised, forward = Tally(), Tally()
    for s in stats.values():
        if s.realised.measurable:
            realised.offered += s.realised.offered
            realised.booked += s.realised.booked
            realised.days |= s.realised.days
        forward.offered += s.forward.offered
        forward.booked += s.forward.booked
    measured = [r for r in rows if r["measured"]]
    valued = [r for r in measured if r["est_monthly_value"] is not None]
    monthly_values = [
        r["est_monthly_value"] for r in measured if r["est_monthly_value"] is not None
    ]
    courts = sum(r["courts"] or 0 for r in rows)
    return {
        "venues": len(rows),
        "venues_with_data": sum(1 for r in rows if r["courts"]),
        "venues_measured": len(measured),
        "venues_valued": len(valued),
        "courts": courts,
        "occupancy": (
            _round(realised.booked / realised.offered, 4) if realised.offered else None
        ),
        "peak_occupancy": _round(
            mean_or_none(r["peak_occupancy"] for r in measured), 4
        ),
        "offpeak_occupancy": _round(
            mean_or_none(r["offpeak_occupancy"] for r in measured), 4
        ),
        "forward_booked": (
            _round(forward.booked / forward.offered, 4) if forward.offered else None
        ),
        "avg_price_per_hour": _round(
            mean_or_none(r["avg_price_per_hour"] for r in rows)
        ),
        "median_price_per_hour": _round(
            median_or_none(r["avg_price_per_hour"] for r in rows)
        ),
        "peak_price_per_hour": _round(
            mean_or_none(r["peak_price_per_hour"] for r in rows)
        ),
        "offpeak_price_per_hour": _round(
            mean_or_none(r["offpeak_price_per_hour"] for r in rows)
        ),
        "est_monthly_value": _round(sum(monthly_values), 0) if monthly_values else None,
        "est_yearly_value": (
            _round(sum(monthly_values) * YEAR_DAYS / RUN_RATE_DAYS, 0)
            if monthly_values
            else None
        ),
        "avg_booked_price": _round(
            mean_or_none(r["avg_booked_price"] for r in measured)
        ),
        "est_monthly_value_per_court": (
            _round(sum(monthly_values) / sum(r["courts"] or 0 for r in valued), 0)
            if monthly_values and sum(r["courts"] or 0 for r in valued)
            else None
        ),
        "courts_per_100k": (
            _round(courts / london_population() * 100_000, 2) if courts else None
        ),
        "observed_days": len(realised.days),
    }


def _group(
    rows: List[dict], field: str, population: Optional[dict] = None
) -> List[dict]:
    groups: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        groups[r[field] or "Unknown"].append(r)
    out = []
    for name, members in groups.items():
        measured = [m for m in members if m["measured"]]
        values = [
            m["est_monthly_value"]
            for m in measured
            if m["est_monthly_value"] is not None
        ]
        courts = sum(m["courts"] or 0 for m in members)
        entry = {
            field: name,
            "venues": len(members),
            "courts": courts,
            "avg_price_per_hour": _round(
                mean_or_none(m["avg_price_per_hour"] for m in members)
            ),
            "occupancy": _round(mean_or_none(m["occupancy"] for m in measured), 4),
            "est_monthly_value": _round(sum(values), 0) if values else None,
        }
        if population is not None:
            pop = population.get(name, {}).get("population")
            entry["population"] = pop
            entry["courts_per_100k"] = (
                _round(courts / pop * 100_000, 2) if pop and courts else None
            )
        out.append(entry)
    return sorted(out, key=lambda e: (e["courts"], e["venues"]), reverse=True)


def _price_bands(rows: List[dict]) -> List[dict]:
    prices = [
        r["avg_price_per_hour"] for r in rows if r["avg_price_per_hour"] is not None
    ]
    if not prices:
        return []
    step = 5 if max(prices) <= 60 else 10
    counts = Counter(int(p // step) * step for p in prices)
    return [{"from": k, "to": k + step, "venues": counts[k]} for k in sorted(counts)]


def _settings(rows: List[dict]) -> List[dict]:
    out = []
    for setting in ("indoor", "outdoor", None):
        members = [r for r in rows if r["setting"] == setting and r["courts"]]
        if not members:
            continue
        measured = [m for m in members if m["measured"]]
        out.append(
            {
                "setting": setting or "unknown",
                "venues": len(members),
                "courts": sum(m["courts"] for m in members),
                "occupancy": _round(mean_or_none(m["occupancy"] for m in measured), 4),
                "avg_price_per_hour": _round(
                    mean_or_none(m["avg_price_per_hour"] for m in members)
                ),
                "est_monthly_value_per_court": _round(
                    mean_or_none(m["est_monthly_value_per_court"] for m in measured), 0
                ),
            }
        )
    return out


def _coverage_by_provider(
    venues: List[dict], freshness: Dict[str, dict], now: datetime
) -> List[dict]:
    by_org: Dict[str, dict] = defaultdict(
        lambda: {"venues": 0, "live": 0, "last_seen": None}
    )
    for v in venues:
        entry = by_org[v["organisation"]]
        entry["venues"] += 1
        seen = (freshness.get(v["composite_key"]) or {}).get("last_seen")
        if seen and now - seen <= _FORWARD_FRESHNESS:
            entry["live"] += 1
        if seen and (entry["last_seen"] is None or seen > entry["last_seen"]):
            entry["last_seen"] = seen
    return sorted(
        ({"organisation": org, **v} for org, v in by_org.items()),
        key=lambda e: e["venues"],
        reverse=True,
    )


def _empty_history_report(sport: str, venues: List[dict], now: datetime) -> dict:
    return {
        "sport": sport,
        "generated_at": now,
        "history_started": None,
        "summary": {
            "venues": len(venues),
            "venues_with_data": 0,
            "venues_measured": 0,
            "courts": 0,
        },
        "venues": [_venue_row(v, None, None, sport) for v in venues],
        "boroughs": [],
        "providers": [],
        "settings": [],
        "price_bands": [],
        "hourly": [],
        "coverage": _coverage_by_provider(venues, {}, now),
        "daily": [],
        "club_sizes": [],
    }


def market_report(sport: str, borough: Optional[str] = None) -> dict:
    if sport not in _SPORTS:
        raise ValueError(f"Unsupported sport: {sport!r}")
    if borough and not borough_name(borough):
        raise ValueError(f"Unknown borough: {borough!r}")
    return _cached(
        f"market:{sport}:{borough}", lambda: _build_market_report(sport, borough)
    )


def _build_market_report(sport: str, borough: Optional[str] = None) -> dict:
    now = _now_london()
    venues = _venues(sport)
    boroughs = resolve_boroughs(
        (v["composite_key"], v["latitude"], v["longitude"]) for v in venues
    )
    area_name = borough_name(borough) if borough else "London"
    if borough:
        venues = [v for v in venues if boroughs.get(v["composite_key"]) == area_name]
    if not _history_exists():
        report = _empty_history_report(sport, venues, now)
        report["venues"] = [
            _venue_row(v, None, boroughs.get(v["composite_key"]), sport) for v in venues
        ]
        report["area"] = {"name": area_name, "slug": borough}
        local_population = (
            borough_population()["boroughs"][area_name]["population"]
            if borough
            else london_population()
        )
        report["capacity"] = capacity(None, local_population)
        report["opportunity"] = _opportunity(
            basis=f"{area_name} · all venues",
            courts=None,
            population=local_population,
            forward_booked=None,
            occupancy=None,
            avg_price_per_hour=None,
            reference_price_per_hour=None,
        )
        report["metric_definitions"] = METRIC_DEFINITIONS
        return report

    buckets, courts = _load_buckets(sport, now)
    keys = {v["composite_key"] for v in venues}
    buckets = [b for b in buckets if b.composite_key in keys]
    stats = venue_stats(buckets, courts)
    rows = [
        _venue_row(
            v, stats.get(v["composite_key"]), boroughs.get(v["composite_key"]), sport
        )
        for v in venues
    ]
    rows.sort(
        key=lambda r: (r["est_monthly_value"] or -1, r["courts"] or 0), reverse=True
    )
    freshness = _coverage(sport, now)
    first_seen = [f["first_seen"] for f in freshness.values() if f["first_seen"]]

    population = borough_population()["boroughs"]
    summary = _summary(rows, stats)
    local_population = (
        population[area_name]["population"] if borough else london_population()
    )
    density_courts = sum(r["courts"] or 0 for r in rows if r["borough"] in population)
    summary["courts_per_100k"] = _round(density_courts / local_population * 100_000)
    reference_price = (
        summary["median_price_per_hour"]
        if not borough
        else market_report(sport)["summary"].get("median_price_per_hour")
    )
    capacity_payload = capacity(density_courts, local_population)
    opportunity = _opportunity(
        basis=f"{area_name} · all venues",
        courts=density_courts,
        population=local_population,
        forward_booked=summary["forward_booked"],
        occupancy=summary["occupancy"],
        avg_price_per_hour=summary["median_price_per_hour"],
        reference_price_per_hour=reference_price,
    )
    daily = defaultdict(Tally)
    for bucket in buckets:
        if bucket.realised and bucket.day < now.date():
            daily[bucket.day].add(bucket)
    sizes = Counter(min(r["courts"], 10) for r in rows if r["courts"])
    return {
        "sport": sport,
        "generated_at": now,
        "history_started": min(first_seen) if first_seen else None,
        "summary": summary,
        "area": {"name": area_name, "slug": borough},
        "opportunity": opportunity,
        "capacity": capacity_payload,
        "metric_definitions": METRIC_DEFINITIONS,
        "daily": [
            {
                "date": day,
                "occupancy": _round(t.booked / t.offered, 4),
                "booking_value": _round(t.value),
                "court_hours": _round(t.offered),
            }
            for day, t in sorted(daily.items())
            if t.offered
        ],
        "club_sizes": [
            {"courts": str(n) if n < 10 else "10+", "venues": sizes[n]}
            for n in range(1, 11)
        ],
        "venues": rows,
        "boroughs": [
            b
            for b in _group(rows, "borough", population)
            if b["borough"] != OUTSIDE_LONDON
        ]
        + [b for b in _group(rows, "borough") if b["borough"] == OUTSIDE_LONDON],
        "providers": _group(rows, "organisation"),
        "settings": _settings(rows),
        "price_bands": _price_bands(rows),
        "hourly": hourly_profile(buckets),
        "coverage": _coverage_by_provider(venues, freshness, now),
        "population": {
            "london": local_population,
            "year": borough_population()["year"],
            "source": borough_population()["source"],
        },
    }


def historical_report(
    sport: str,
    days: int = 90,
    borough: Optional[str] = None,
    composite_key: Optional[str] = None,
) -> dict:
    market = market_report(sport, borough)
    venues = [
        v
        for v in market["venues"]
        if not composite_key or v["composite_key"] == composite_key
    ]
    keys = [v["composite_key"] for v in venues]

    def build():
        now = _now_london()
        exists = _rows(
            "SELECT to_regclass('public.daily_price_snapshot') IS NOT NULL AS ok"
        )[0]["ok"]
        params = dict(
            sport=sport, since=now.date() - timedelta(days=days - 1), keys=keys
        )
        bounds = (
            _rows(
                """
            SELECT MIN(observed_on) AS first_day, MAX(observed_on) AS last_day,
                   COUNT(DISTINCT observed_on) AS observed_days
            FROM public.daily_price_snapshot
            WHERE sport=:sport AND observed_on >= :since AND composite_key=ANY(:keys)
        """,
                **params,
            )[0]
            if exists and keys
            else {"first_day": None, "last_day": None, "observed_days": 0}
        )
        pairs = (
            _rows(
                """
            WITH baseline AS (
                SELECT * FROM public.daily_price_snapshot
                WHERE sport=:sport AND observed_on=:baseline AND composite_key=ANY(:keys)
            )
            SELECT p.observed_on, p.composite_key,
                   AVG(p.price_per_hour / NULLIF(b.price_per_hour, 0)) AS ratio,
                   COUNT(*) FILTER (WHERE b.price_per_hour > 0) AS ratio_samples,
                   COUNT(*) AS matched_samples,
                   AVG(b.price_per_hour) AS before, AVG(p.price_per_hour) AS after
            FROM public.daily_price_snapshot p
            JOIN baseline b USING (sport, composite_key, dow, starting_time, duration_min)
            WHERE p.sport=:sport AND p.observed_on >= :since AND p.composite_key=ANY(:keys)
            GROUP BY p.observed_on, p.composite_key
        """,
                **params,
                baseline=bounds["first_day"],
            )
            if bounds["first_day"]
            else []
        )
        report = summarise_price_pairs(bounds, pairs)
        names = {v["composite_key"]: v["venue_name"] for v in venues}
        for v in report["venues"]:
            v["venue_name"] = names[v["composite_key"]]
        supply_exists = _rows(
            "SELECT to_regclass('public.daily_supply_snapshot') IS NOT NULL AS ok"
        )[0]["ok"]
        supply = (
            _rows(
                """
            SELECT observed_on AS date, COUNT(*) AS venues, SUM(courts) AS courts
            FROM public.daily_supply_snapshot
            WHERE sport = :sport AND observed_on >= :since AND composite_key = ANY(:keys)
            GROUP BY observed_on ORDER BY observed_on
        """,
                sport=sport,
                since=now.date() - timedelta(days=days - 1),
                keys=keys,
            )
            if supply_exists and keys
            else []
        )
        return {
            "sport": sport,
            "generated_at": now,
            "prices": report,
            "supply": [dict(r) for r in supply],
        }

    return _cached(f"history:{sport}:{days}:{borough}:{composite_key}", build)


def venue_report(sport: str, composite_key: str) -> Optional[dict]:
    if sport not in _SPORTS:
        raise ValueError(f"Unsupported sport: {sport!r}")
    market = market_report(sport)
    venue = next(
        (v for v in market["venues"] if v["composite_key"] == composite_key), None
    )
    if venue is None:
        return None
    return _cached(
        f"venue:{sport}:{composite_key}",
        lambda: _build_venue_report(sport, venue, market),
    )


_TIMELINE_STOP_WORDS = {
    "the",
    "and",
    "ltd",
    "limited",
    "club",
    "clubs",
    "centre",
    "center",
    "sports",
    "sport",
    "leisure",
    "venue",
    "courts",
    "court",
    "padel",
    "tennis",
    "badminton",
    "squash",
    "pickleball",
    "london",
    "uk",
    "gll",
}


def _name_tokens(*values) -> set:
    tokens = set()
    for value in values:
        for word in re.findall(r"[a-z0-9]+", (value or "").lower()):
            if len(word) >= 4 and word not in _TIMELINE_STOP_WORDS:
                tokens.add(word)
    return tokens


def _first_tracked_dates(sport: str, keys: List[str]) -> Dict[str, object]:
    """Earliest observation day per venue, from whichever history exists."""
    keys = [key for key in keys if key]
    if not keys:
        return {}
    first: Dict[str, object] = {}
    if _history_exists():
        rows = _rows(
            """
            SELECT composite_key, MIN(first_seen) AS first_seen
            FROM public.slot_history
            WHERE sport = :sport AND composite_key = ANY(:keys)
            GROUP BY composite_key
            """,
            sport=sport,
            keys=keys,
        )
        for row in rows:
            if row["first_seen"]:
                first[row["composite_key"]] = row["first_seen"].date()
    supply_exists = _rows(
        "SELECT to_regclass('public.daily_supply_snapshot') IS NOT NULL AS ok"
    )[0]["ok"]
    if supply_exists:
        rows = _rows(
            """
            SELECT composite_key, MIN(observed_on) AS first_day
            FROM public.daily_supply_snapshot
            WHERE sport = :sport AND composite_key = ANY(:keys)
            GROUP BY composite_key
            """,
            sport=sport,
            keys=keys,
        )
        for row in rows:
            day = row["first_day"]
            key = row["composite_key"]
            if day and (key not in first or day < first[key]):
                first[key] = day
    return first


def _planning_matches(venue: dict, applications: List[dict]) -> List[dict]:
    """Applications that plausibly belong to this venue.

    A same-site distance is the strongest signal; a distinctive name token or
    an exact postcode catches applications filed at a neighbouring address.
    """
    tokens = _name_tokens(venue.get("venue_name"), venue.get("organisation"))
    postcode = re.sub(r"[^A-Z0-9]", "", (venue.get("postcode") or "").upper())
    matches = []
    for application in applications:
        text = " ".join(
            str(application.get(field) or "")
            for field in ("description", "applicant", "agent", "borough")
        )
        application_postcode = re.sub(
            r"[^A-Z0-9]", "", (application.get("postcode") or "").upper()
        )
        same_site = application["distance_miles"] <= 0.12
        same_postcode = bool(postcode) and application_postcode == postcode
        name_match = bool(tokens and tokens & _name_tokens(text))
        if same_site or same_postcode or name_match:
            # A distinctive name is the strongest signal, then an exact
            # postcode, then merely being at the same site.
            score = -3 if name_match else -2 if same_postcode else -1
            matches.append((score, application))
    matches.sort(key=lambda pair: (pair[0], pair[1]["distance_miles"]))
    return [application for _, application in matches[:6]]


def _planning_event(title: str, day, application: dict) -> dict:
    return {
        "kind": "planning",
        "date": day.isoformat() if hasattr(day, "isoformat") else day,
        "title": title,
        "detail": application.get("description"),
        "reference": application.get("reference"),
        "url": application.get("url"),
        "status": application.get("status"),
        "courts": application.get("courts"),
    }


def _planning_events(applications: List[dict]) -> List[dict]:
    """First submitted and first decided application, matching the club story."""
    submitted = [a for a in applications if a.get("submitted")]
    approved = [
        a
        for a in applications
        if a.get("status") in ("Permitted", "Conditions") and a.get("decided")
    ]
    refused = [
        a for a in applications if a.get("status") == "Rejected" and a.get("decided")
    ]
    events = []
    if submitted:
        # Prefer an application that actually proposes courts over a signage
        # or advertisement consent filed at the same site.
        with_courts = [a for a in submitted if a.get("courts")]
        application = min(with_courts or submitted, key=lambda a: a["submitted"])
        events.append(
            _planning_event(
                "First planning application submitted",
                application["submitted"],
                application,
            )
        )
    if approved:
        with_courts = [a for a in approved if a.get("courts")]
        application = min(with_courts or approved, key=lambda a: a["decided"])
        events.append(
            _planning_event(
                "First planning application approved",
                application["decided"],
                application,
            )
        )
    elif refused:
        with_courts = [a for a in refused if a.get("courts")]
        application = min(with_courts or refused, key=lambda a: a["decided"])
        events.append(
            _planning_event(
                "First planning application refused",
                application["decided"],
                application,
            )
        )
    events.sort(key=lambda event: event["date"], reverse=True)
    return events


def _club_timeline(sport: str, venue: dict) -> List[dict]:
    events = []
    first = _first_tracked_dates(sport, [venue["composite_key"]]).get(
        venue["composite_key"]
    )
    if first:
        events.append(
            {
                "kind": "tracked",
                "date": first.isoformat() if hasattr(first, "isoformat") else first,
                "title": "Availability first tracked",
                "detail": "First public court availability recorded by Sportscanner.",
            }
        )
    if venue.get("latitude") is not None and venue.get("longitude") is not None:
        nearby = applications_within(sport, venue["latitude"], venue["longitude"], 0.5)
        events.extend(_planning_events(_planning_matches(venue, nearby)))
    events.sort(key=lambda event: event["date"], reverse=True)
    return events


def _operator_key(name: str) -> str:
    """A venue-name prefix that groups an operator's sites.

    `organisation` is the booking platform (Padel Mates, Playtomic, Better),
    not the club operator. "Padium Canary Wharf" and "Padium Cardiff" share
    the distinctive first token; "Rocket Padel Ilford" and "Rocket Padel
    Beckton" share "rocket".
    """
    for token in re.findall(r"[a-z0-9]+", (name or "").lower()):
        if len(token) >= 4 and token not in _TIMELINE_STOP_WORDS:
            return token
    return (name or "").lower().strip()


def _operator_timeline(sport: str, venue: dict, market: dict) -> List[dict]:
    key = _operator_key(venue["venue_name"])
    peers = [
        peer for peer in market["venues"] if _operator_key(peer["venue_name"]) == key
    ][:12]
    first = _first_tracked_dates(sport, [peer["composite_key"] for peer in peers])
    rows = []
    for peer in peers:
        kind = "tracked"
        day = first.get(peer["composite_key"])
        label = "Availability first tracked"
        if peer.get("latitude") is not None and peer.get("longitude") is not None:
            nearby = applications_within(
                sport, peer["latitude"], peer["longitude"], 0.5
            )
            approved = [
                application
                for application in _planning_matches(peer, nearby)
                if application.get("status") in ("Permitted", "Conditions")
                and application.get("decided")
                and application.get("courts")
            ]
            if approved:
                application = min(approved, key=lambda a: a["decided"])
                day = application["decided"]
                kind = "planning"
                label = "Planning approved"
        rows.append(
            {
                "composite_key": peer["composite_key"],
                "venue_name": peer["venue_name"],
                "borough": peer.get("borough"),
                "date": (day.isoformat() if hasattr(day, "isoformat") else day),
                "kind": kind,
                "label": label,
            }
        )
    rows.sort(key=lambda row: row["date"] or "", reverse=True)
    rows.sort(key=lambda row: row["date"] is None)
    return rows[:8]


def _build_venue_report(sport: str, venue: dict, market: dict) -> dict:
    now = _now_london()
    buckets, _ = (
        _load_buckets(sport, now, venue["composite_key"])
        if _history_exists()
        else ([], {})
    )

    nearby = []
    if venue["latitude"] is not None and venue["longitude"] is not None:
        for other in market["venues"]:
            if (
                other["composite_key"] == venue["composite_key"]
                or other["latitude"] is None
                or other["longitude"] is None
            ):
                continue
            miles = _haversine_miles(
                venue["latitude"],
                venue["longitude"],
                other["latitude"],
                other["longitude"],
            )
            if miles <= NEARBY_RADIUS_MILES:
                nearby.append({**other, "distance_miles": round(miles, 2)})
    nearby.sort(key=lambda o: o["distance_miles"])

    benchmark_fields = (
        "avg_price_per_hour",
        "peak_price_per_hour",
        "offpeak_price_per_hour",
        "occupancy",
        "forward_booked",
        "est_monthly_value_per_court",
    )
    benchmarks = [
        {
            "metric": f,
            "venue": venue[f],
            "local_median": _round(median_or_none(o[f] for o in nearby), 4),
            "london_median": _round(median_or_none(o[f] for o in market["venues"]), 4),
        }
        for f in benchmark_fields
    ]

    # Listed price per hour of day, split weekday/weekend.
    price_grid: Dict[Tuple[str, int], Tally] = defaultdict(Tally)
    for b in buckets:
        price_grid[("weekend" if b.dow >= 6 else "weekday", b.hour)].add(b)
    upcoming: Dict[str, Tally] = defaultdict(Tally)
    for b in buckets:
        if not b.realised:
            upcoming[b.day.isoformat()].add(b)

    measured_peers = [v for v in market["venues"] if v["est_monthly_value"] is not None]
    daily = defaultdict(Tally)
    for bucket in buckets:
        if bucket.realised and bucket.day < now.date():
            daily[bucket.day].add(bucket)
    return {
        "sport": sport,
        "generated_at": now,
        "venue": venue,
        "metric_definitions": METRIC_DEFINITIONS,
        "ranks": {
            "est_monthly_value": _rank(
                market["venues"], "est_monthly_value", venue["composite_key"]
            ),
            "occupancy": _rank(market["venues"], "occupancy", venue["composite_key"]),
            "est_monthly_value_per_court": _rank(
                market["venues"], "est_monthly_value_per_court", venue["composite_key"]
            ),
            "of": len(measured_peers),
            "occupancy_of": sum(v["occupancy"] is not None for v in market["venues"]),
        },
        "benchmarks": benchmarks,
        "nearby": nearby[:8],
        "nearby_count": len(nearby),
        "daily": [
            {
                "date": day,
                "occupancy": _round(t.booked / t.offered, 4),
                "booking_value": _round(t.value),
                "court_hours": _round(t.offered),
            }
            for day, t in sorted(daily.items())
            if t.offered
        ],
        "hourly": hourly_profile(buckets),
        "price_by_hour": [
            {"day_type": day_type, "hour": hour, "price_per_hour": _round(t.avg_price)}
            for (day_type, hour), t in sorted(price_grid.items())
            if t.avg_price is not None
        ],
        "upcoming": [
            {
                "date": day,
                "booked": _round(t.booked / t.offered, 4) if t.offered else None,
                "court_hours": round(t.offered, 1),
            }
            for day, t in sorted(upcoming.items())
        ],
        "timeline": _club_timeline(sport, venue),
        "operator_timeline": _operator_timeline(sport, venue, market),
        "peak_definition": "Weekdays 07:00-09:00 and 17:00-22:00, plus all weekend hours",
    }


def overview() -> dict:
    """Cross-sport headline numbers for the insights landing page."""

    def build():
        sports = []
        for sport in _SPORTS:
            report = market_report(sport)
            sports.append(
                {
                    "sport": sport,
                    "history_started": report["history_started"],
                    **report["summary"],
                }
            )
        return {"generated_at": _now_london(), "sports": sports}

    return _cached("overview", build)
