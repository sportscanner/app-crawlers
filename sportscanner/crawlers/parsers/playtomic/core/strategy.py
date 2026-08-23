"""
Playtomic strategy implementations.

tenant_id is a stable UUID assigned once when a club registers on Playtomic — it
never changes.  Rather than rediscovering it on every crawl run, the mapping is
hardcoded here.  When a new venue is added to venues.json, look up its tenant_id
once (e.g. from api.playtomic.io/v1/tenants) and add it to SLUG_TO_TENANT_ID.

The availability API returns slots in local venue time (UK time), so no timezone
conversion is needed.  Slots are aggregated by (start_time, duration) across
courts; `spaces` reflects the number of courts bookable at that time.

Booking URL note
----------------
The Playtomic API tenant_uid (stored as slug in venues.json) doesn't always match
the website URL.  Trailing dashes and triple-dash sequences in some tenant_uids
don't appear in the website URL.  _BOOKING_SLUG_OVERRIDES maps the API slug to
the correct website slug; None means no working public page exists for that venue.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

import sportscanner.storage.postgres.tables
from sportscanner.crawlers.anonymize.proxies import get_with_proxy_fallback_on_403
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
from sportscanner.crawlers.parsers.playtomic.core.schema import PlaytomicResource
from sportscanner.logger import logging

PLAYTOMIC_ORGANISATION_WEBSITE = "https://playtomic.com"

_AVAILABILITY_API = "https://playtomic.com/api/clubs/availability"
PADEL_SPORT_ID = "PADEL"
# Confirmed live against a real dual-sport venue (Tennis England Club,
# tenant_id 2a31c6ce-b212-4448-abd2-b05a6bbde784): returns real, distinctly
# priced slots separate from that same venue's PADEL response.
TENNIS_SPORT_ID = "TENNIS"
# Confirmed live against Kensington Pickleball Club (Indoors & Outdoors),
# tenant_id 40805261-42ab-41b9-b35e-73bc5d4f299e: returns real, distinctly
# priced slots (£28/hr) separate from that venue's PADEL/other-sport responses.
PICKLEBALL_SPORT_ID = "PICKLEBALL"

# Where the API tenant_uid differs from the website URL slug, list the correct
# website slug here.  None = no public booking page found for this venue.
_BOOKING_SLUG_OVERRIDES: Dict[str, Optional[str]] = {
    "powerleague-shoreditch-": "powerleague-shoreditch",
    "battersea-park-millennium-arena-": "battersea-park-millennium-arena",
    "padel-social-club---earls-court": "padel-social-club-earls-court",
    "padel-social-club---the-o2": "padel-social-club-the-o2",
    "rocks-lane---chiswick": "rocks-lane-chiswick",
    "padel-people---wimbledon": "padel-people-wimbledon",
    "tour-padel---avery-hill-campus-": "tour-padel-avery-hill-campus",
    "rocks-lane-@-dyrham-park-country-club": "rocks-lane-dyrham-park-country-club",
    "powerleague-mill-hill-": "powerleague-mill-hill",
    "rocks-lane---barnes": "rocks-lane-barnes-london",
    "padel-4-everyone---noak-hill": "padel4everyone-harold-hill-central-park",
    "the-padel-hub-n20-ltd": "the-padel-hub-n20-north-london",
    "brent-x": "social-sports-brent-cross",
    "padel-waltham-abbey": "padel-district-waltham-abbey",
    "the-london-padel-club": "padel-padel-eltham",
    "wembley-padel": "social-sports-wembley",
}
# Note: newly added venues whose API tenant_uids match their public club-page
# slugs need no override.


def _booking_url(tenant_uid: str, slot_date: date) -> Optional[str]:
    if tenant_uid in _BOOKING_SLUG_OVERRIDES:
        website_slug = _BOOKING_SLUG_OVERRIDES[tenant_uid]
        if website_slug is None:
            return None
        return f"{PLAYTOMIC_ORGANISATION_WEBSITE}/clubs/{website_slug}?date={slot_date.isoformat()}"
    return f"{PLAYTOMIC_ORGANISATION_WEBSITE}/clubs/{tenant_uid}?date={slot_date.isoformat()}"


_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-GB,en;q=0.9",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

# Stable mapping of venues.json slug (= Playtomic tenant_uid) → tenant_id (UUID).
# tenant_id never changes — add new venues here when they are added to venues.json.
SLUG_TO_TENANT_ID: Dict[str, str] = {
    "the-hive-london": "4ab18f91-d6bb-440e-b890-4d5422a786fc",
    "powerleague-shoreditch-": "2ab75436-9bb0-4e9c-9a6f-b12931a9ca4a",
    "battersea-park-millennium-arena-": "0e86011b-7857-4bc9-b594-9334047316a4",
    "padel-social-club---earls-court": "1c97a3d1-ded7-4c4b-808e-8c37bb1b2a1f",
    "padel-box-bermondsey": "a95b1ddd-ea5a-4516-86a8-cf3825ebe760",
    "georgians-padel": "7c3575d5-8285-4199-a9e1-961118269bfe",
    "rocks-lane---barnes": "e2ec82b3-3862-4e42-90bb-bb41f59e737d",
    "barn-elms-sports-centre": "6e1734ed-38bd-42bf-a336-e0e2aa74d0e2",
    "padel-social-club---the-o2": "9e79c4f9-3c2e-4fb8-a01f-ae514dc7e351",
    "rocks-lane---chiswick": "9c95ac87-5273-47a9-bf67-342c566caf79",
    "padel-people---wimbledon": "4256b5d8-8d35-45bb-8c6d-e425afe94692",
    "the-108": "67d29714-a14b-4c66-9eaf-aade676be071",
    "brent-x": "f76ac01f-b201-4f26-af36-5dc0d550a5c5",
    "padel-tree-finchley": "29e2d319-bea5-4957-9196-cda1b9bccb92",
    "wembley-padel": "c583d30b-3381-418d-8d4d-73c2460de8c7",
    "the-london-padel-club": "60baf499-42ac-4dc6-8a55-4226a50697d2",
    "the-padel-hub-n20-ltd": "7a6f7a17-5a73-4468-9329-56c901f1ceba",
    "boxx-padel": "c95356d5-4ec5-4b24-bf61-2c7396174d66",
    "catford-padel-collective": "d690fb50-37bf-4e3f-bb13-294282bc3552",
    "tour-padel---avery-hill-campus-": "df114d7a-6bf3-427d-8d7a-d4e88865efda",
    "powerleague-mill-hill-": "12338c4b-e078-4b3a-a50e-5568293183b3",
    "padel-tree-brentford": "9b5b1052-d193-4b6f-a813-ca7a55dd9592",
    "cw-padel-club": "69777c06-4f64-4788-b62f-d235362abbe8",
    "padel-and-coffee": "95bc71fb-6a16-4004-b7a8-59d24cfaf4a6",
    "s3-padel-sutton": "82c2a7fc-e943-45ed-9752-1116d37a818b",
    "padel-united-erith": "fbd1bfa1-a581-48fb-9592-7ec3ceac538c",
    "woodford-wells-club": "182340a7-6a14-4c18-b6e2-c47a9e8df267",
    "padel-waltham-abbey": "5ccd5197-0083-411e-9e7f-de0a418c5b69",
    "powerleague-romford": "fa87d0cb-5c08-4249-bc61-71c6d408abf7",
    "padel-4-everyone---noak-hill": "48991fdc-d2d4-415a-b9ab-c3c911083d80",
    "rocks-lane-@-dyrham-park-country-club": "e24d075d-b5a5-4a0d-a303-2c7e92d9e598",
    "padel-tree-arkley": "3b16a151-703d-45cd-b164-0f8422b56f03",
    "purley-sports-club": "3bfdd0e1-b304-4779-8574-5270ac0d74fa",
    # Tennis venue (confirmed live: 9 tennis courts + 4 padel courts, sport_id=TENNIS
    # returns real, distinctly-priced slots from this same tenant_id).
    "open-jan-2025-tennis-england-club": "2a31c6ce-b212-4448-abd2-b05a6bbde784",
    # Added August 2026. tenant_ids read off each venue's public club page
    # (playtomic.com/clubs/{slug} embeds tenant_id in its booking links) and
    # verified anonymously against the availability API for a real date.
    # Padel Social Club - Paddington: 4 padel courts, ~£80/hr.
    "padel-social-club-paddington": "0cf8af2e-6122-4c75-8195-c5ab4de58922",
    # Pickleball-only venues (sport_id=PICKLEBALL, no PADEL/TENNIS response).
    # West London Pickleball Club: 4 courts, ~£20/hr.
    "west-london-pickleball-club": "2af6b5fa-0c25-414b-87ae-93032eea1084",
    # Kensington Pickleball Club (Indoors & Outdoors): ~£28/hr, indoor + outdoor.
    "kensington-pickleball-club-indoors-outdoors": "40805261-42ab-41b9-b35e-73bc5d4f299e",
    # Newly audited London venues (August 2026)
    # Racketeer: 13 padel courts + 1 pickleball court, Park Royal / Harlesden NW10.
    "racketeer": "549a1bc8-d63e-43d4-b632-5a313e299845",
    # Padel Pals Sydenham: 4 padel courts, Bell Green Retail Park SE26.
    "padel-pals": "774d4c71-f3fc-4640-9a0f-83434c14879c",
    # Bannatyne Grove Park: 3 padel courts, Marvels Lane SE12.
    "bannatyne-grove-park": "b064140d-3157-4c93-aed1-15afd7e5b993",
    # Bannatyne Chafford Hundred: 3 padel courts, Grays RM16.
    "bannatyne-chafford-hundred": "d1906935-630b-466f-b918-2861ec29f5a6",
    # Padel Play London: 3 padel courts, Hermitage Road / Finsbury Park N4.
    "padel-play-london": "70041e91-3274-4fe7-8490-b3c4ca4c9450",
    # Padel United Willesden: 1 padel court, Willesden Sports Centre NW10.
    "padel-united-willesden": "d95b0249-2c67-4bc0-8392-8ad405801dab",
    # Powerleague Watford: 4 padel courts, Queens School Bushey WD23.
    "powerleague-watford": "4fe8baeb-0201-4dfb-a2c8-126705a1a0ed",
    # Kensington Tennis Club - Holland Park Villas: 2 tennis courts W8.
    "kensington-tennis-club-holland-park-villas-indoors-outdoors": "17073a7b-e226-484a-82cf-d2ca0dab9751",
    # Kensington Tennis Club - King's Road: 1 tennis court SW10.
    "kensington-tennis-club-kings-road": "6e4e1447-5ed3-44ec-98c5-5a202e98e251",
    # Ezeepadel Weybridge: 4 padel courts, KT13.
    "ezeepadel-weybridge": "1eb90d21-84ba-4f46-b523-61dffef0739f",
    # Epping Golf Course: 1 padel court, CM16.
    "epping-golf-course": "b4f2b7d2-b93d-4117-8483-4b6162b95302",
}


_LONDON_TZ = ZoneInfo("Europe/London")


def _utc_to_london(time_str: str, slot_date: date) -> time:
    """Convert a UTC HH:MM:SS string to UK local time for the given date.

    The date is required so ZoneInfo can apply the correct BST/GMT offset —
    Europe/London is UTC+1 in summer and UTC+0 in winter.
    """
    h, m, s = map(int, time_str.split(":"))
    dt_utc = datetime(
        slot_date.year, slot_date.month, slot_date.day, h, m, s, tzinfo=timezone.utc
    )
    return dt_utc.astimezone(_LONDON_TZ).time().replace(second=0, microsecond=0)


def _format_price(price_str: str) -> str:
    """Convert '68 GBP' to '£68.00'."""
    parts = price_str.strip().split()
    try:
        amount = float(parts[0])
        return f"£{amount:.2f}"
    except (ValueError, IndexError):
        return price_str


def _add_minutes(t: time, minutes: int) -> time:
    dummy = datetime(2000, 1, 1, t.hour, t.minute, t.second)
    return (dummy + timedelta(minutes=minutes)).time()


def _resources_to_unified(
    resources: List[PlaytomicResource],
    venue: sportscanner.storage.postgres.tables.SportsVenue,
    fetch_date: date,
    category: str = "Padel",
) -> List[UnifiedParserSchema]:
    """Aggregate availability across courts into one record per (start_time, duration)."""
    slot_map: Dict[tuple, List[str]] = defaultdict(list)

    for resource in resources:
        for slot in resource.slots:
            slot_map[(slot.start_time, slot.duration)].append(slot.price)

    results: List[UnifiedParserSchema] = []
    for (start_time_str, duration_min), prices in slot_map.items():
        try:
            start_t = _utc_to_london(start_time_str, fetch_date)
        except (ValueError, AttributeError):
            logging.warning(
                f"Playtomic: unparseable start_time '{start_time_str}' — skipping"
            )
            continue

        results.append(
            UnifiedParserSchema(
                category=category,
                starting_time=start_t,
                ending_time=_add_minutes(start_t, duration_min),
                date=fetch_date,
                price=_format_price(prices[0]),
                spaces=len(prices),
                composite_key=venue.composite_key,
                last_refreshed=datetime.now(),
                booking_url=_booking_url(venue.slug, fetch_date),
            )
        )

    return results


# ---------------------------------------------------------------------------
# Strategy classes
# ---------------------------------------------------------------------------


class PlaytomicRequestStrategy(AbstractRequestStrategy):
    """Stub — Playtomic crawler bypasses the standard per-venue request loop."""

    @override
    def generate_request_details(
        self,
        sports_venue: sportscanner.storage.postgres.tables.SportsVenue,
        fetch_date: date,
        token: Optional[str] = None,
    ) -> List[RequestDetailsWithMetadata]:
        return [
            RequestDetailsWithMetadata(
                url=_AVAILABILITY_API,
                headers=_HEADERS,
                payload=None,
                metadata=AdditionalRequestMetadata(
                    category="Padel",
                    date=fetch_date,
                    sportsCentre=sports_venue,
                ),
            )
        ]


class PlaytomicTennisRequestStrategy(AbstractRequestStrategy):
    """Stub — Playtomic crawler bypasses the standard per-venue request loop."""

    @override
    def generate_request_details(
        self,
        sports_venue: sportscanner.storage.postgres.tables.SportsVenue,
        fetch_date: date,
        token: Optional[str] = None,
    ) -> List[RequestDetailsWithMetadata]:
        return [
            RequestDetailsWithMetadata(
                url=_AVAILABILITY_API,
                headers=_HEADERS,
                payload=None,
                metadata=AdditionalRequestMetadata(
                    category="Tennis",
                    date=fetch_date,
                    sportsCentre=sports_venue,
                ),
            )
        ]


class PlaytomicPickleballRequestStrategy(AbstractRequestStrategy):
    """Stub — Playtomic crawler bypasses the standard per-venue request loop."""

    @override
    def generate_request_details(
        self,
        sports_venue: sportscanner.storage.postgres.tables.SportsVenue,
        fetch_date: date,
        token: Optional[str] = None,
    ) -> List[RequestDetailsWithMetadata]:
        return [
            RequestDetailsWithMetadata(
                url=_AVAILABILITY_API,
                headers=_HEADERS,
                payload=None,
                metadata=AdditionalRequestMetadata(
                    category="Pickleball",
                    date=fetch_date,
                    sportsCentre=sports_venue,
                ),
            )
        ]


class PlaytomicResponseParserStrategy(AbstractResponseParserStrategy):
    """Pass-through — content is already List[UnifiedParserSchema]."""

    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        return raw_response.content


class PlaytomicAvailabilityFetcher:
    """Fetches per-(venue, date) availability using hardcoded tenant_ids.

    Not a BaseCrawler strategy — PlaytomicPadelCrawler/PlaytomicTennisCrawler
    override ScraperCoroutines and drive this helper directly (the availability
    API is queried by tenant_id query-param, not the per-venue URL loop the
    standard crawlers use). `sport_id`/`category` are threaded through per
    instance rather than hardcoded, so the same fetcher class serves both
    sports on the identical API/response shape (Playtomic's response schema
    carries no sport field either way — the value requested is the value you get).
    """

    def __init__(self, sport_id: str = PADEL_SPORT_ID, category: str = "Padel"):
        self.sport_id = sport_id
        self.category = category

    async def fetch_venue_date(
        self,
        client: httpx.AsyncClient,
        venue: sportscanner.storage.postgres.tables.SportsVenue,
        tenant_id: str,
        fetch_date: date,
        semaphore: asyncio.Semaphore,
    ) -> List[UnifiedParserSchema]:
        """Fetch and parse availability for one venue + date.

        A small number of venues (confirmed: Woodford Wells Club, Tour Padel -
        Avery Hill Campus) get HTTP 403 on every date within a given GitHub
        Actions run, in a large minority of runs - each run gets one fresh
        runner IP, and whether that IP is already blocklisted by Playtomic's
        WAF for that specific venue is luck of the draw (see
        docs/clubs/playtomic.md). On 403, retry via the rotating proxy (a fresh
        connection is a fresh shot at a different exit IP) rather than treating
        it as "no slots".
        """
        try:
            async with semaphore:
                resp = await get_with_proxy_fallback_on_403(
                    client,
                    _AVAILABILITY_API,
                    params={
                        "tenant_id": tenant_id,
                        "date": fetch_date.isoformat(),
                        "sport_id": self.sport_id,
                    },
                    headers={
                        **_HEADERS,
                        "referer": f"{PLAYTOMIC_ORGANISATION_WEBSITE}/clubs/{venue.slug}",
                    },
                    timeout=30,
                    log_label=f"Playtomic {venue.venue_name} {fetch_date}",
                )
            if resp is None:
                return []
            resources = [PlaytomicResource(**r) for r in resp.json()]
            slots = _resources_to_unified(
                resources, venue, fetch_date, category=self.category
            )
            logging.debug(
                f"Playtomic: {venue.venue_name} {fetch_date} → {len(slots)} slot groups"
            )
            return slots
        except httpx.HTTPStatusError as exc:
            logging.warning(
                f"Playtomic: HTTP {exc.response.status_code} for "
                f"{venue.venue_name} on {fetch_date}"
            )
            return []
        except Exception as exc:
            logging.error(
                f"Playtomic: failed for {venue.venue_name} on {fetch_date}: {exc}"
            )
            return []
