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
    # squash slug name (not just its version) changed on v2:
    # "squash-court-40min" (v1) -> "squash-40min" (v2)
    "squash": [
        ("squash-40min/v2", "squash-court-40min"),
    ],
    # Pickleball slug spelling changes between v1 and v2: legacy v1
    # is plural ("pickleball-40mins", no version suffix); v2 dropped the "s"
    # ("pickleball-40min/v2"). Plural/v1 as primary + singular/v2 as fallback
    # covers legacy and migrated venues.
    "pickleball": [
        ("pickleball-40mins", "pickleball-40min/v2"),
        ("pickleball-60mins", "pickleball-60min/v2"),
    ],
    # Tennis outdoor courts default to v2 slug.
    "tennis": [
        ("tennis-court-outdoor/v2", "tennis-court-outdoor"),
    ],
}

# (sport, venue_slug) -> activity-slug pairs, for venues that don't follow the default
_VENUE_OVERRIDES: Dict[Tuple[str, str], List[ActivitySlugPair]] = {
    # Richmond upon Thames venues expose a single "badminton-court" activity
    # (v2 only; v1 404s) of mixed durations rather than 40/60min splits.
    ("badminton", "shene-sports-and-fitness-centre"): [
        ("badminton-court/v2", "badminton-court"),
    ],
    ("badminton", "hampton-sports-and-fitness-centre"): [
        ("badminton-court/v2", "badminton-court"),
    ],
    ("badminton", "teddington-sports-centre"): [
        ("badminton-court/v2", "badminton-court"),
    ],
    ("badminton", "whitton-sports-and-fitness-centre"): [
        ("badminton-court/v2", "badminton-court"),
    ],
    # Teddington Sports Centre runs 45-minute squash sessions.
    ("squash", "teddington-sports-centre"): [
        ("squash-45min/v2", "squash-45min"),
    ],
    # Richmond upon Thames venues expose "pickleball-court" rather than 40/60min splits.
    ("pickleball", "shene-sports-and-fitness-centre"): [
        ("pickleball-court/v2", "pickleball-drop-in/v2"),
    ],
    ("pickleball", "hampton-sports-and-fitness-centre"): [
        ("pickleball-court/v2", "pickleball-court"),
    ],
    ("pickleball", "teddington-sports-centre"): [
        ("pickleball-court/v2", "pickleball-court"),
    ],
    ("pickleball", "whitton-sports-and-fitness-centre"): [
        ("pickleball-court/v2", "pickleball-court"),
    ],
    # Britannia has standard pickleball-60min as well as ticketed pickleball-drop-in.
    ("pickleball", "britannia-leisure-centre"): [
        ("pickleball-60min/v2", "pickleball-drop-in/v2"),
    ],
    # Multi-court tennis venues (indoor, outdoor, dome, clay):
    ("tennis", "islington-tennis-centre"): [
        ("tennis-court-outdoor/v2", "tennis-court-outdoor"),
        ("tennis-court-indoor/v2", "tennis-court-indoor"),
    ],
    ("tennis", "lee-valley-hockey-and-tennis-centre"): [
        ("tennis-court-outdoor/v2", "tennis-court-outdoor"),
        ("tennis-court-indoor/v2", "tennis-court-indoor"),
    ],
    ("tennis", "sutton-sports-village"): [
        ("tennis-court-clay/v2", "tennis-court-clay"),
        ("tennis-court-dome/v2", "tennis-court-dome"),
        ("tennis-court-outdoor/v2", "tennis-court-outdoor"),
    ],
}


def activity_slug_pairs(sport: str, venue_slug: str) -> List[ActivitySlugPair]:
    """(primary, fallback) activity-slug pairs to request for this sport/venue."""
    return _VENUE_OVERRIDES.get((sport, venue_slug), _DEFAULTS[sport])

