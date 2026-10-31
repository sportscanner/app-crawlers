from datetime import date, datetime, time

from sportscanner.crawlers.parsers.better.core.strategy import (
    BetterLeisureResponseParserStrategy,
    _derive_indoor,
)
from sportscanner.crawlers.parsers.core.schemas import (
    AdditionalRequestMetadata,
    RawResponseData,
    RequestDetailsWithMetadata,
    UnifiedParserSchema,
)
from sportscanner.crawlers.pipeline import fill_estimated_prices
from sportscanner.storage.postgres.tables import SportsVenue


def _better_venue() -> SportsVenue:
    return SportsVenue(
        composite_key="c0891bdc",
        organisation="Better / GLL (Greenwich Leisure Limited)",
        organisation_website="https://www.better.org.uk",
        venue_name="Platinum Jubilee Leisure Centre",
        slug="platinum-jubilee-leisure-centre",
        postcode="UB7 9NQ",
        address="Rowlheys Place, West Drayton, London, UB7 9NQ",
        latitude=51.500906,
        longitude=-0.470589,
        sports=["badminton", "pickleball"],
    )


def _better_raw_response(price) -> RawResponseData:
    venue = _better_venue()
    return RawResponseData(
        content=[
            {
                "starts_at": {"format_12_hour": "07:00am", "format_24_hour": "07:00"},
                "ends_at": {"format_12_hour": "08:00am", "format_24_hour": "08:00"},
                "duration": "60min",
                "price": price,
                "category_slug": "pickleball-60min",
                "date": "2026-11-02",
                "venue_slug": venue.slug,
                "spaces": 2,
                "name": "Pickleball 60min",
            }
        ],
        status_code=200,
        headers={},
        requestMetadata=RequestDetailsWithMetadata(
            url="https://better-admin.org.uk/api/activities/venue/platinum-jubilee-leisure-centre/activity/pickleball-60min/v2/times?date=2026-11-02",
            headers={},
            metadata=AdditionalRequestMetadata(
                category="Pickleball",
                date=date(2026, 11, 2),
                sportsCentre=venue,
            ),
        ),
    )


def test_better_missing_price_is_unknown_not_zero():
    # Better returns `price: null` for early sessions at some venues. That is
    # "not quoted", not "free" - it must not become £0.00.
    slots = BetterLeisureResponseParserStrategy().parse(
        _better_raw_response({"is_estimated": True, "formatted_amount": None})
    )
    assert slots[0].price == ""


def test_better_present_price_is_preserved():
    slots = BetterLeisureResponseParserStrategy().parse(
        _better_raw_response({"is_estimated": False, "formatted_amount": "£10.10"})
    )
    assert slots[0].price == "£10.10"


def test_fill_estimated_prices_replaces_missing_better_price():
    missing = BetterLeisureResponseParserStrategy().parse(
        _better_raw_response({"is_estimated": True, "formatted_amount": None})
    )[0]
    priced = UnifiedParserSchema(
        category="Pickleball",
        starting_time=time(9, 0),
        ending_time=time(10, 0),
        date=date(2026, 11, 2),
        price="£10.10",
        spaces=2,
        composite_key=missing.composite_key,
        last_refreshed=datetime.now(),
        booking_url=None,
    )

    filled = fill_estimated_prices([missing, priced])

    assert filled[0].price == "~£10.10"


def test_derive_indoor_tennis_reads_court_name():
    # Confirmed live against Islington Tennis Centre / Lee Valley: Better's
    # raw slot `name` field carries "Tennis Court - Indoor"/"- Outdoor" for
    # venues with mixed court types.
    assert _derive_indoor("Tennis", "Tennis Court - Indoor") is True
    assert _derive_indoor("Tennis", "Tennis Court - Outdoor") is False


def test_derive_indoor_tennis_unrecognised_name_is_unknown():
    assert _derive_indoor("Tennis", "Tennis Court") is None


def test_derive_indoor_pickleball_always_indoor():
    # Every Better pickleball court is a converted sports-hall court - no
    # indoor/outdoor split exists in the activity-slug config.
    assert _derive_indoor("Pickleball", "Pickleball 40 min") is True


def test_derive_indoor_not_applicable_for_badminton_and_squash():
    assert _derive_indoor("Badminton", "Badminton Court 1") is None
    assert _derive_indoor("Squash", "Squash Court 1") is None
