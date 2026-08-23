"""
Padel Mates strategy implementations.

Padel Mates (padelmates.se / padelmates.co) is a Swedish booking platform
running a React SPA against two backend APIs. Availability viewing is fully
anonymous (only completing a booking needs a Firebase login), and the API has
no TLS-fingerprint WAF: plain httpx works.

API shape (reverse-engineered from the SPA bundle, main.*.js):

    GET {FAST_API_BASE}/club/?club_id={short_name}
        Club metadata. Accepts either the club's short_name (the URL slug,
        e.g. "rocketpadelilford") or its MongoDB _id.

    GET {FAST_API_BASE}/player/player_booking/all_courts_slot_prices_v2
        ?club_id={MongoDB _id}&start_datetime={epoch ms}&end_datetime={epoch ms}
        Returns {"allSlots": [...]}: one entry per bookable (court, start,
        duration). Booked/full times are simply absent from the response.
        Timestamps MUST be epoch milliseconds - epoch seconds pass the int
        validation but land in 1970 and produce a misleading 404 "No active
        pricelist found for the club".

The club_id for the availability endpoint must be the club's _id, not its
short_name (the /club/ endpoint accepts both, the booking endpoint does not),
so the mapping is hardcoded in CLUB_SLUG_TO_CLUB_ID. The _id is stable in
practice; re-derive it via GET /club/?club_id={short_name} when adding a venue.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import sportscanner.storage.postgres.tables
from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.core.interfaces import (
    AbstractRequestStrategy,
    AbstractResponseParserStrategy,
)
from sportscanner.crawlers.parsers.core.schemas import (
    AdditionalRequestMetadata,
    RawResponseData,
    RequestDetailsWithMetadata,
    UnifiedParserSchema,
)
from sportscanner.crawlers.parsers.padelmates.core.schema import PadelMatesSlot
from sportscanner.logger import logging

PADEL_MATES_ORGANISATION_WEBSITE = "https://padelmates.se"
_AVAILABILITY_API = (
    "https://fastapi-production-fargate.padelmates.io"
    "/player/player_booking/all_courts_slot_prices_v2"
)

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

# venues.json slug (= Padel Mates short_name) -> club _id required by the
# availability endpoint. Add new venues here when they are added to venues.json.
CLUB_SLUG_TO_CLUB_ID: Dict[str, str] = {
    "rocketpadelilford": "788fa2c66535421aabc60fd27f941c42",
    "rocketpadelbattersea": "n8T0bz1PtMa1WhVElJ7Eclg0ooj2",
    "rocketpadelbeckton": "f953765495194a299e49f49674d69a41",
    "padium": "47d2eb0db7194a9dbd29783c3a2a82ad",
    "instantpadelatcanadawater": "10a9c13109b94d148565f4920c55dd62",
    "playtimepadeltooting": "01184befd26e434aa78ddbe807a2cb84",
    "playtimepadelkingston": "eWQ7RJEfJHbzjTGFnUumVhBNa1A3",
    "playtimepadeldagenham": "9c605bfae8494a34bef3910eb770e427",
    "playtimepadelbrentwood": "49ca3a172b9b4d8fba84c5be70707294",
    "playtimepadelolympicpark": "322ff0f1486f4cefbe0d501decf6d8e6",
    "playtimepadeltolworth": "1bRETAfhG7a4XlYVf1PW7p0eSKD3",
    "houseofracquet": "d11965b0f8c24527bf36491e6c32a39f",
    "farmpadel": "b399a322258e4e868425dbee75b5bd53",
    "noakhillpadel": "8333407a31f14792a0bf97f968bf6706",
    "padelxtrabeckenham": "d86d35c277df41e883b5fe8cdb752e0d",
}

_LONDON_TZ = ZoneInfo("Europe/London")


def _london_day_bounds_utc_ms(fetch_date: date) -> tuple[int, int]:
    """Epoch-millisecond bounds of a London calendar day, as the API expects
    them (the SPA sends day boundaries computed in the club's timezone). A
    London-day range starting at UTC midnight would clip evening slots."""
    start_utc = datetime(
        fetch_date.year, fetch_date.month, fetch_date.day, tzinfo=_LONDON_TZ
    )
    end_utc = start_utc + timedelta(days=1)
    return int(start_utc.timestamp() * 1000), int(end_utc.timestamp() * 1000)


def _booking_url(slug: str) -> str:
    return f"{PADEL_MATES_ORGANISATION_WEBSITE}/club/{slug}"


class PadelMatesRequestStrategy(AbstractRequestStrategy):
    """One availability request per (venue, date). Query params are baked into
    the URL because BaseCrawler's shared fetch loop issues plain GETs."""

    @override
    def generate_request_details(
        self,
        sports_venue: sportscanner.storage.postgres.tables.SportsVenue,
        fetch_date: date,
        token: Optional[str] = None,
    ) -> List[RequestDetailsWithMetadata]:
        club_id = CLUB_SLUG_TO_CLUB_ID.get(sports_venue.slug)
        if not club_id:
            logging.warning(
                f"Padel Mates: venue slug '{sports_venue.slug}' not in CLUB_SLUG_TO_CLUB_ID"
            )
            return []
        start_ms, end_ms = _london_day_bounds_utc_ms(fetch_date)
        url = (
            f"{_AVAILABILITY_API}"
            f"?club_id={club_id}"
            f"&start_datetime={start_ms}&end_datetime={end_ms}"
        )
        return [
            RequestDetailsWithMetadata(
                url=url,
                headers=_HEADERS,
                payload=None,
                metadata=AdditionalRequestMetadata(
                    category="Padel",
                    date=fetch_date,
                    booking_url=_booking_url(sports_venue.slug),
                    sportsCentre=sports_venue,
                ),
            )
        ]


class PadelMatesResponseParserStrategy(AbstractResponseParserStrategy):
    """Aggregates per-(court, start, duration) entries into one record per
    (start, duration) across courts, same convention as Playtomic: `spaces`
    is how many courts are bookable at that exact slot."""

    def _transform_raw_response_to_typed(
        self, api_response: dict
    ) -> List[PadelMatesSlot]:
        return [PadelMatesSlot(**slot) for slot in api_response.get("allSlots", [])]

    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        if not raw_response.content:
            return []
        try:
            slots = self._transform_raw_response_to_typed(raw_response.content)
        except Exception as e:
            logging.error(
                f"Unable to apply PadelMatesSlot schema to raw API json:\n{e!r}"
            )
            return []

        # reservedIntersection=True means the slot overlaps an existing
        # reservation or open match (e.g. a 60-min option clipping a booked
        # hour): it appears in the price list but cannot be cleanly booked,
        # so treat it as unavailable rather than counting it as a free court.
        bookable = [s for s in slots if not s.reservedIntersection]

        slot_map: Dict[tuple, List[PadelMatesSlot]] = defaultdict(list)
        for slot in bookable:
            start_local = slot.startDatetime.astimezone(_LONDON_TZ)
            # The API's London-day window can include a slot stamped 23:00 UTC
            # on the previous day (= London midnight); bucket by local datetime.
            slot_map[
                (start_local.replace(second=0, microsecond=0), slot.duration)
            ].append(slot)

        unified_schema_output: List[UnifiedParserSchema] = []
        for (start_dt, duration_min), group in sorted(slot_map.items()):
            unified_schema_output.append(
                UnifiedParserSchema(
                    category=raw_response.requestMetadata.metadata.category,
                    starting_time=start_dt.time(),
                    ending_time=(start_dt + timedelta(minutes=duration_min)).time(),
                    date=start_dt.date(),
                    price=f"£{group[0].price:.2f}",
                    spaces=len(group),
                    composite_key=raw_response.requestMetadata.metadata.sportsCentre.composite_key,
                    last_refreshed=raw_response.requestMetadata.metadata.last_refreshed,
                    booking_url=raw_response.requestMetadata.metadata.booking_url,
                )
            )
        return unified_schema_output
