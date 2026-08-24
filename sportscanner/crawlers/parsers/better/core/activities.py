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
    # ("pickleball-40min/v2"). As of August 2026 every tracked London venue has
    # migrated to v2 (the previously "v1-only" five included), so singular/v2
    # is primary and plural/v1 stays as fallback for any straggler venue that
    # has not migrated. Note the customer-facing bookings.better.org.uk URL
    # never carries the "/v2" segment either way - see public_activity_slug().
    "pickleball": [
        ("pickleball-40min/v2", "pickleball-40mins"),
        ("pickleball-60min/v2", "pickleball-60mins"),
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


def public_activity_slug(activity_slug: str) -> str:
    """Strip the API-only "/v2" version suffix for building customer-facing
    bookings.better.org.uk URLs.

    The public booking site's URL scheme never includes a version segment,
    regardless of whether the activity resolves through v1 or v2 internally:
    confirmed via the `slug` field on `.../categories/{sport}`, which is
    always the bare activity name (e.g. "pickleball-60min", not
    "pickleball-60min/v2") even for venues that are v2-only. Embedding the
    raw activity-slug (with "/v2") into a booking_url instead produces a
    dead customer-facing link with a spurious extra path segment.
    """
    return activity_slug.split("/v2")[0]

