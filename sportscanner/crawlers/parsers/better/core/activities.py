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
    # Pickleball is itself mid-rollout, same as badminton/squash, but the slug
    # spelling changes *between* v1 and v2 instead of staying fixed: legacy v1
    # is plural ("pickleball-40mins", no version suffix); v2 dropped the "s"
    # ("pickleball-40min/v2"). A handful of venues (confirmed: score-leisure-centre,
    # barking-sporthouse-and-gym, waltham-forest-feel-good-centre,
    # walthamstow-leisure-centre, leytonstone-leisure-centre) are still v1-only —
    # v2 404s/500s for them. The rest of the pickleball roster (confirmed: 17 of
    # 22 venues, including lee-valley-velopark, woolwich-waves-leisure-centre,
    # the-plumstead-centre) have migrated and are v2-only — v1 answers with a
    # generic "date should be within the valid days you are able to view" 422
    # (not a clean 404) because the plural activity no longer exists for them, so
    # plural/v1 as primary + singular/v2 as fallback covers both groups.
    # (Previously the fallback here was still plural ("pickleball-40mins/v2"),
    # which 500s — that's what caused woolwich-waves/plumstead/lee-valley to sit
    # with zero pickleball rows despite the venues genuinely having availability.)
    "pickleball": [
        ("pickleball-40mins", "pickleball-40min/v2"),
        ("pickleball-60mins", "pickleball-60min/v2"),
    ],
}

# (sport, venue_slug) -> activity-slug pairs, for venues that don't follow the default
_VENUE_OVERRIDES: Dict[Tuple[str, str], List[ActivitySlugPair]] = {
    # shene doesn't split badminton into 40/60min — it exposes a single
    # "badminton-court" activity (v2 only; v1 404s) of mixed durations.
    ("badminton", "shene-sports-and-fitness-centre"): [
        ("badminton-court/v2", "badminton-court"),
    ],
    # Neither venue follows the standard 40/60min duration split for pickleball at
    # all — discovered via GET /api/activities/venue/{slug}/categories/pickleball,
    # which lists a venue's real activity slugs under a sport category (the most
    # reliable way to find the correct slug when the 40min/60min guesses 422).
    # Both are v2-only ("v1_slug": null in that response).
    #
    # shene exposes "pickleball-court" (a resources/court-booking activity, same
    # shape as badminton/squash) alongside "pickleball-drop-in" (a ticketed
    # session activity — different response shape, untested here since it had no
    # scheduled sessions in the visible window; investigate its parsing if it
    # ever 200s with non-empty data and looks wrong).
    ("pickleball", "shene-sports-and-fitness-centre"): [
        ("pickleball-court/v2", "pickleball-drop-in/v2"),
    ],
    # britannia only has the ticketed "pickleball-drop-in" activity, no separate
    # court-booking activity at all.
    ("pickleball", "britannia-leisure-centre"): [
        ("pickleball-drop-in/v2", "pickleball-drop-in"),
    ],
}


def activity_slug_pairs(sport: str, venue_slug: str) -> List[ActivitySlugPair]:
    """(primary, fallback) activity-slug pairs to request for this sport/venue."""
    return _VENUE_OVERRIDES.get((sport, venue_slug), _DEFAULTS[sport])
