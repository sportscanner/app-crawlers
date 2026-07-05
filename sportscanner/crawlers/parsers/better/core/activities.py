"""Declarative per-sport / per-venue activity-slug config for Better/GLL.

Better/GLL is mid-rollout of a "/v2" times endpoint, done per-venue and
per-activity-duration. For each activity we try a primary slug first and fall
back to a secondary if the primary returns an HTTP error (a not-yet-migrated
venue 422-ing v2, or a migrated venue 422-ing the legacy v1). Most venues share
the per-sport default; the handful that deviate live in _VENUE_OVERRIDES.

Adding a venue quirk is a one-line data entry here rather than an `if` branch in
the request builder. Each entry is a list of (primary_slug, fallback_slug) pairs;
one HTTP request is generated per pair.
"""
from typing import Dict, List, Tuple

ActivitySlugPair = Tuple[str, str]

# sport -> default (primary, fallback) activity-slug pairs
_DEFAULTS: Dict[str, List[ActivitySlugPair]] = {
    "badminton": [
        ("badminton-40min/v2", "badminton-40min"),
        ("badminton-60min/v2", "badminton-60min"),
    ],
    # squash's slug name (not just its version) changed on v2:
    # "squash-court-40min" (v1) -> "squash-40min" (v2)
    "squash": [
        ("squash-40min/v2", "squash-court-40min"),
    ],
    # pickleball's v2 endpoint currently 500s for every venue, so v1 is primary
    # and v2 is the fallback here — inverse ordering to badminton/squash.
    "pickleball": [
        ("pickleball-40mins", "pickleball-40mins/v2"),
        ("pickleball-60mins", "pickleball-60mins/v2"),
    ],
}

# (sport, venue_slug) -> activity-slug pairs, for venues that don't follow the default
_VENUE_OVERRIDES: Dict[Tuple[str, str], List[ActivitySlugPair]] = {
    # shene doesn't split badminton into 40/60min — it exposes a single
    # "badminton-court" activity (v2 only; v1 404s) of mixed durations.
    ("badminton", "shene-sports-and-fitness-centre"): [
        ("badminton-court/v2", "badminton-court"),
    ],
    # lee-valley uses a distinct pickleball activity slug
    ("pickleball", "lee-valley-velopark"): [
        ("pickleball-60mins-court", "pickleball-60mins-court/v2"),
    ],
}


def activity_slug_pairs(sport: str, venue_slug: str) -> List[ActivitySlugPair]:
    """(primary, fallback) activity-slug pairs to request for this sport/venue."""
    return _VENUE_OVERRIDES.get((sport, venue_slug), _DEFAULTS[sport])
