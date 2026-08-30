from datetime import date

from sportscanner.crawlers.parsers.playtomic.core.schema import (
    PlaytomicResource,
    PlaytomicSlot,
)
from sportscanner.crawlers.parsers.playtomic.core.strategy import (
    _RESOURCE_FEATURES_PATTERN,
    _resources_to_unified,
)
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.storage.postgres.utils import generate_composite_key

ORGANISATION_WEBSITE = "https://playtomic.com"


def _make_venue(slug: str) -> SportsVenue:
    return SportsVenue(
        composite_key=generate_composite_key([ORGANISATION_WEBSITE, slug]),
        organisation="Playtomic",
        organisation_website=ORGANISATION_WEBSITE,
        venue_name="Test Venue",
        slug=slug,
        postcode="E1 6AN",
        address="London",
        latitude=51.5,
        longitude=-0.1,
        sports=["padel"],
    )


def test_resources_to_unified_splits_indoor_and_outdoor_courts():
    # Confirmed live against a real mixed venue (Padel and Coffee): merging
    # courts of different indoor/outdoor status into one grouping key hides
    # the split entirely and makes an indoor/outdoor filter impossible.
    resources = [
        PlaytomicResource(
            resource_id="indoor-court-1",
            start_date="2026-09-01",
            slots=[PlaytomicSlot(start_time="19:00:00", duration=60, price="20 GBP")],
        ),
        PlaytomicResource(
            resource_id="outdoor-court-1",
            start_date="2026-09-01",
            slots=[PlaytomicSlot(start_time="19:00:00", duration=60, price="15 GBP")],
        ),
    ]
    resource_indoor_map = {"indoor-court-1": True, "outdoor-court-1": False}
    venue = _make_venue("padel-and-coffee")

    results = _resources_to_unified(
        resources,
        venue,
        date(2026, 9, 1),
        category="Padel",
        resource_indoor_map=resource_indoor_map,
    )

    assert len(results) == 2
    by_indoor = {r.indoor: r for r in results}
    assert by_indoor[True].spaces == 1
    assert by_indoor[False].spaces == 1
    assert by_indoor[True].starting_time == by_indoor[False].starting_time


def test_resources_to_unified_same_type_courts_still_aggregate():
    resources = [
        PlaytomicResource(
            resource_id="indoor-court-1",
            start_date="2026-09-01",
            slots=[PlaytomicSlot(start_time="19:00:00", duration=60, price="20 GBP")],
        ),
        PlaytomicResource(
            resource_id="indoor-court-2",
            start_date="2026-09-01",
            slots=[PlaytomicSlot(start_time="19:00:00", duration=60, price="20 GBP")],
        ),
    ]
    resource_indoor_map = {"indoor-court-1": True, "indoor-court-2": True}
    venue = _make_venue("racketeer")

    results = _resources_to_unified(
        resources,
        venue,
        date(2026, 9, 1),
        category="Padel",
        resource_indoor_map=resource_indoor_map,
    )

    assert len(results) == 1
    assert results[0].spaces == 2
    assert results[0].indoor is True


def test_resources_to_unified_unknown_indoor_status_defaults_none():
    resources = [
        PlaytomicResource(
            resource_id="unmapped-court",
            start_date="2026-09-01",
            slots=[PlaytomicSlot(start_time="19:00:00", duration=60, price="20 GBP")],
        ),
    ]
    venue = _make_venue("some-venue")

    results = _resources_to_unified(
        resources, venue, date(2026, 9, 1), category="Padel", resource_indoor_map={}
    )

    assert len(results) == 1
    assert results[0].indoor is None


def test_resource_features_pattern_extracts_indoor_outdoor():
    # Confirmed live: the club page embeds this shape backslash-escaped
    # (\"resourceId\":...) - callers strip backslashes before matching, so
    # the pattern itself matches the plain (unescaped) form.
    content = (
        '"resources":[{"resourceId":"abc-123","name":"Court 1 Indoor",'
        '"sport":"PADEL","features":["indoor","single","turf"]},'
        '{"resourceId":"def-456","name":"Court 2 Outdoor",'
        '"sport":"PADEL","features":["outdoor","single","concrete"]}]'
    )
    matches = _RESOURCE_FEATURES_PATTERN.findall(content)
    assert matches == [
        ("abc-123", '"indoor","single","turf"'),
        ("def-456", '"outdoor","single","concrete"'),
    ]
