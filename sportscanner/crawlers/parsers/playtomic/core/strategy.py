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
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from curl_cffi.requests import AsyncSession as CurlAsyncSession

import sportscanner.storage.postgres.tables
from sportscanner.crawlers.anonymize.proxies import (
    get_with_proxy_fallback_on_403,
    next_impersonate_profile,
)
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
    "s3-padel-finchley-road": "113065cd-202c-46e7-9ef4-a2af650983cf",
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
    # UK-wide additions (October 2026): venues resolved from the
    # UK public inventory. tenant_ids read from each venue's public
    # playtomic.com/clubs/{slug} page and verified anonymously against the
    # availability API for a live date (423/432 returned court resources).
    "22-padel": "1d36c4dc-4114-475a-921c-bb1da58a5074",
    "ace-padel-club": "da10d793-57b1-4789-b04d-4ca45651efa9",
    "ace-padel-culcheth": "64dcc2e1-64b0-4628-8ab1-928cca3c8365",
    "ace-padel-lytham-st-annes": "59daebc0-ab7e-4dfb-a15a-9e0ef2de44e5",
    "ace-padel-milton": "85ce7924-87fe-4f18-9946-bccbdc8cc7fe",
    "ace-padel-stoke": "09009c91-0418-4ce8-9b41-42233523e286",
    "adlington-padel": "cffcc0b3-76d3-476c-9ea4-b9949bcaee02",
    "agri-padel": "f656b849-9d0f-4b27-a329-e007f5ddbdfd",
    "akebar-park": "fd1d3069-c209-432d-93a6-40f715e1f8ed",
    "alderney-tennis-and-padel-club": "511840e3-8912-4a65-802d-7251e2128764",
    "alsager-padel": "64cf46ac-1d58-4696-81c5-b9f76f4baa3b",
    "apex-padel-bury": "2d3c7cf2-cf85-44be-825c-ecfd709a422f",
    "atc-padel": "4feb9af7-79ce-4a44-b34e-f1b20336abac",
    "atmos-padel-chesterfield": "8e99c127-ce28-4397-939f-ca3597c930ac",
    "atmos-padel-darlington": "e4ac2c1f-0837-44f4-92a7-fd5414b804ef",
    "atmos-padel-lowther-gardens": "fe6026e7-4994-49e2-87f5-27316774a115",
    "atmos-padel-potters-bar": "a70c49ff-12b0-4266-83f7-6f19cc400494",
    "atmos-padel-south-shields": "9370e079-ea40-41a4-9545-09d68b727bf6",
    "atmos-padel-worthing": "5b809ed6-9116-411a-9d61-d4c67bf5a54a",
    "axclub": "c7d9ea23-5003-4243-8093-7b421872a588",
    "bannatyne-beechdown": "6942a98a-4a96-4077-a9ad-a9159d5a61d4",
    "bannatyne-ingleby-barwick": "176b4a7f-f8ac-4608-8ed5-e43ec5749818",
    "bannatyne-livingston": "2651b2b0-581b-4ab7-a35f-f350c8eff92f",
    "bannatyne-norwich": "c99778e3-378a-4f40-8909-1cd814111e20",
    "barnsgrove": "3121306a-ffd4-4c14-8bfd-f35f1bd80790",
    "barnsley-padel-club": "1f6de465-192a-4199-aed8-c5a77024baa4",
    "barons-fitness": "06fa0d3b-7c24-4fd9-b108-8488dc6d2671",
    "battersea-park-millennium-arena": "0e86011b-7857-4bc9-b594-9334047316a4",
    "belfast-boat-club-padel": "531604fb-4acc-41a4-923f-a308573c376f",
    "benton-hall-golf-country-club": "14edeb00-da05-4704-af88-da61aae3cf20",
    "border-padel-co": "a684b348-b21b-4ef6-8520-102f48179606",
    "border-padel-co-central": "aa4c3fc3-3e35-40bb-9b9f-b1546e7d77a7",
    "bounc": "3ef27a5d-a35a-474e-a588-12b5b20fe8c1",
    "bradshaws-padel": "44278dce-517a-448d-bbec-1ac9cc545936",
    "brakepoint-padel-club": "b0ef6008-1587-4cce-acb8-ccd796ca4a39",
    "brampton-heath-golf-and-padel": "6f0344f0-7631-411b-a4fe-e1231cc15554",
    "brandesburton-rackets-club": "e285988c-6e6f-4b50-aacc-fddb882a448a",
    "branston-golf-and-country-club": "80f9247d-9f59-4d81-9f5e-c7c15b06ed24",
    "bunsay-padel": "e1844eb4-a9fc-47dc-803e-a97ce0220700",
    "burnley-padel-club": "fab79489-d533-4dbf-b3ac-52d8c2150b8c",
    "carbon-padel-club": "49f2c02d-eb18-4ff6-ac15-998707103e74",
    "carbon-padel-club-rochdale": "41b98e8d-68f5-45d2-82ae-daae862611e2",
    "cardiff-house-of-sport": "59f3dc44-5c87-4491-829b-e10181ac6f0e",
    "casadelpadelmalton": "3f275403-bf26-4010-a07a-b0803d4f31fe",
    "castle-padel-club": "44ec05be-2f8c-474a-9ed9-2d6675dedbd1",
    "centre-court-padel": "35c5611d-7146-48f0-bc33-06b5f19be611",
    "chalk-padel": "1422f717-53f6-4498-bcf7-00ab7c3466d1",
    "chalke-valley-padel-club": "6aadb21d-5240-4278-b044-a9353a8d7d2b",
    "cheshire-padel-crewe-vagrants-sports-club": "805ef29e-4598-4bf3-b549-d5d5b7be6618",
    "chiltern-padel-club": "dc30f744-d0e6-405f-938f-8e824f2f4464",
    "city-padel-exeter": "3198f517-efdd-44ff-94cc-50dd13491da0",
    "city-padel-plymouth": "ff706ca4-f764-43e4-8832-461197b2b4a5",
    "city-padel-taunton": "82c6e8b1-6286-4b52-8f64-aea8869211a2",
    "clonoe-padel": "9047365e-f47d-4035-ab4d-7a1b8aae89c1",
    "club-de-padel-sheffield": "d90f3cd9-880f-4ff2-8aca-47e7ec8d0bd0",
    "core-padel-nuneaton": "be97d572-fcf4-4bfb-a4a4-2256f85b2008",
    "core-padel-tyseley": "5ef5f05e-bdad-4aa2-a29f-b3551ac5980c",
    "cotswold-padel-club": "583d5196-ae31-4cd8-b6d5-506e94a8ec19",
    "cottesmore-hotel-golf-and-country-club": "f855d0e1-4660-4ee9-8498-7fddcbeaf1d1",
    "court-de-padel-hull": "8504cf3f-8e85-479c-9406-1abd5c996d93",
    "court-de-padel-prestatyn": "a597e437-506c-4650-9c68-73922e52a158",
    "courtfit-padel-cobham": "ab23b3e4-b416-493a-9c4d-a113bb5740a2",
    "cross-court-padel": "388665a8-1a76-43e7-822e-ed7c515e610f",
    "cross-padel": "95a60171-171f-458a-83d1-a08e527cf4a7",
    "d1-padel": "d445b511-2469-4f86-b03d-91ff0451647c",
    "derbyshire-tennis-centre": "2f4df0f6-dcdf-4cc7-a52f-2c0491456e7b",
    "destination-padel-cheadle": "0f131b2a-6ee3-4d0a-9ac3-04309db24238",
    "destination-padel-northwich": "96d85b68-b8a1-43a0-a803-2a45ad4e4d6c",
    "destino-padel": "74a26272-1b5c-4994-8cf5-7450edfee42a",
    "deuce-padel-centre": "b812aac7-3b18-421e-be62-17d2945103b8",
    "dhm-padel": "d965d56c-3d95-4c61-8d81-98835988702c",
    "doddington-padel-courts": "0de3ed3a-8a48-4f44-9f44-446925275c8c",
    "draycote-hotel-padel-club": "dbd7edfe-c59a-4047-9c6c-d81e1239fda1",
    "driffield-padel-club": "c392145d-c0d5-4015-adc5-383dde9519cf",
    "driffield-padel-court": "09c6f9fe-288b-4b78-b2ca-a2b453934874",
    "dynamic-padel": "1fecae87-2b91-411b-a156-528b1f893fd9",
    "east-coast-padel": "7502a187-e166-4f96-aeb8-f1e58be58d69",
    "east-coast-padel-cleethorpes": "69d4501d-5c08-47a8-86c2-871a463db98c",
    "essendon-padel-club": "88f92dcc-342f-4852-b1b6-19b2276c3e0a",
    "east-dorset-padel": "da25ad46-c6d2-4266-b9da-2a00863b1919",
    "eastbourne-padel-club": "8907d4f9-38fc-416e-a302-116dbab2dfea",
    "eaton-park-padel": "a3a0620a-f1d0-4f0f-aab0-b81aa1530c8e",
    "eixo-padel": "95887934-f304-4194-a732-f6b6b9915188",
    "encourt-padel-wellness": "fb272fc4-ae55-40c5-bec5-60b9bd63aa83",
    "esperpadel": "014ad116-de54-4c96-a26d-831d1cdd14c9",
    "everybody-padel-the-barony": "e101525e-44e4-4f03-83ed-27fc9f7aef14",
    "everybody-padel-wilmslow": "3bee2ee2-9b55-460f-a648-10145ae75c2d",
    "factory-padel-uk": "5f6636d8-d97c-4f82-8fa8-2a2e8004da9c",
    "flex-padel": "bae1d89d-b4b7-4441-95a7-6fd583abcb78",
    "forever-padel": "d9e83566-5042-40ac-912a-c68e601d6117",
    "foundry-padel-club": "c3dd8518-a10a-4665-8578-d75bbca68daa",
    "fr-padel": "fb01cb77-7d64-47f8-bede-d96f090a0f5e",
    "frodsham-padel-club": "10857bbe-a646-4a95-a761-b59f52e06c9c",
    "galgorm-castle": "ae82f05e-c799-4c23-90c0-c160e597b580",
    "gatwick-padel": "2b3554c6-9d9a-4472-9567-39f86d701531",
    "glass-padel-club": "5e91a282-8cd0-4b61-b1e8-f7187e396a74",
    "glossop-padel": "f1f70b05-4aba-4122-bf05-7885b8fb0cb2",
    "goat-haus": "cd866f00-a08d-460d-bf4c-c9ac93e139d6",
    "gotpadelclub": "04ef428f-e4a6-46a6-a99a-f20f2e70aa3b",
    "grace-dieu-padel": "0893c37b-8306-45d7-bedc-37db2dd9e195",
    "gsm-padel": "b8d79cdf-d8c7-4e2e-b3d4-4c2b0b05328a",
    "hampton-in-arden-sports-club": "594478a5-02d1-4572-a59b-7766efea2730",
    "harbour-padel-littlehampton": "78fd4b40-5944-4e33-a38a-be6afff63e9e",
    "harrogate-spa-tennis-centre": "d6d04c01-6101-455f-8968-8de9f75bf384",
    "hartford-tennis-club": "d5112ac7-bf6c-4d09-9d11-665aef11416a",
    "hascombe-farm": "618fb2da-0c0b-426b-9fd5-b3d8949cf922",
    "hastings-padel-freedom-leisure": "578f9021-98a6-479b-afc3-d8ac4a9d5b0b",
    "hatton-sports-club": "4186328f-8b51-4e61-b8ec-481a29983e11",
    "headlands-farm-padel-club": "b4ec1161-a27c-4318-9b90-a8b34cc6c3e0",
    "heart-of-padel": "30cee76c-1156-4547-acfd-8b070a6753ef",
    "henley-padel": "0b02ad06-c15f-4fa0-bfad-147f5d84b6c2",
    "hexham-tennis-club": "cd3bf519-a3c6-4882-9cb2-dcaf8ce2bcee",
    "hg5-padel": "1c8f9c71-40f3-4e5a-ac6f-ebc4638c2a55",
    "holcombe-brook-sports-club": "edc1a0c7-1343-4018-b156-e8a49c01b818",
    "house-of-padel-belfast": "14a123d1-7e2d-405f-b7d0-792ec110a6bf",
    "ignite-padel-chesire-oaks": "0ce0d36f-9d1e-4c59-971d-ab23d0c77da3",
    "ignite-padel-speke": "9bb1d698-6a9a-4f05-9d51-d152ed4616e4",
    "its-padel": "1ce660d3-a7a8-4919-b7cd-c7d608b59454",
    "jaxx-padel": "835f85fa-a51d-4a62-9ce3-c48e459bed3e",
    "just-padel-blackpool": "7a0ab011-dfc0-4cd5-af83-4631b7d8763c",
    "just-padel-bolton": "ce3bdf50-01a0-4b68-9ead-5cd1b83a224a",
    "just-padel-preston": "dc2e4b7e-c0c5-4d0c-a716-53477e016bbb",
    "just-play-padel": "24c1162b-732f-423b-a6bb-070763964436",
    "kingfisher-padel-club": "f16ea267-d166-4d6a-88ca-b579412c600e",
    "kip-and-nook-padel": "05ebc118-ffd9-463e-a34c-7efccbc39802",
    "korta": "7ea9f212-7cc0-427d-ba55-20eae4893ac7",
    "lacey-green-loosley-row-padel-tennis": "fbefee6e-829f-4e09-bc7b-67ea018aa143",
    "lake-y": "492064d5-26c1-4b7d-aa73-6dcd52cf16c9",
    "last-sun-dance-padel-club": "69546bad-2cd7-4cb1-bc78-1ac349063a8a",
    "lets-go-padel-ballyclare": "cdf59d2f-7b6f-4cae-8eb5-262a0a090777",
    "lets-go-padel-ballygawley": "25be6dfa-871f-4fc4-b5ea-e4edacc2adfd",
    "lets-go-padel-ballymoney": "c73d2d9d-1cc7-4b5e-a8c4-aa8a77b9ab26",
    "lets-go-padel-carryduff": "f740073c-7452-4ffc-965d-238db8d43092",
    "lets-go-padel-crumlin-road": "9e156443-7671-48ef-9d69-0133cacf32d6",
    "lets-go-padel-derry": "39c39bf4-9108-49d7-ad0d-cd4b24c8c2da",
    "lets-go-padel-lurgan": "0e4498bc-ccb2-4394-8022-85b38d69223d",
    "lets-go-padel-omagh": "dc10fb31-1d70-4bff-882e-c47d6d70b5ff",
    "lets-go-padel-shorts-east-belfast": "67b531f5-5bc3-4baf-91df-9dee1a419cfe",
    "life-leisure-grand-central": "807cf7e9-9024-492f-b667-1b1f5ff51c55",
    "life-leisure-houldsworth-village-stockport": "d1e55ec3-025d-4cb2-8163-896de91810ae",
    "louth-padel-co": "db75c79e-8f6b-4ae4-b1f6-1e76789b7cf4",
    "mad-swans-mendips": "f2f20ce3-a70c-4259-ab60-c90381e3cefa",
    "mad-swans-south-downs": "ac282413-1e8f-4de6-b4af-b6a891c1e774",
    "manchester-padel-club": "811ddf98-330d-4902-939d-b5a6f2e8ff38",
    "manor-padel-club": "bc996828-c136-4f66-80e3-510523b847c3",
    "manton-sports-club": "e6a90e2f-2aa5-4e36-a7f0-af934989189a",
    "maurice-chandler-sports-leisure-centre": "475a67b8-9ff2-4ba4-a9a9-bad26f42f65e",
    "mickleover-padel-club": "6f55ff03-610d-4a1f-8058-50cd333376b0",
    "midfield-padel-wellness-centre": "94193940-d635-4a94-b0b1-e56c6567468a",
    "moorwood-padel": "21f4f377-2110-4a4b-95f9-bcd39edf16b5",
    "neighbourhood-padel": "2389141a-e433-4ce4-9c84-ad7db30ef14b",
    "neo-padel-gainsborough": "8672aa2a-eb55-4137-b3bc-132f087a2cb2",
    "nexo-padel": "dbc31ce4-c018-40bb-81cf-1b17430e3fb1",
    "northampton-county-lawn-tennis-club": "bcb8346f-c37a-41da-a024-c2cb8fa9e6a9",
    "on-padel-t1-golf-sports-village": "6a5ea6f6-bc7c-420f-9995-1d477b4963e4",
    "optimum-padel": "5d3d374a-958f-4012-83b0-afaedcb750f0",
    "overstone-padel": "3e9492bc-8d9b-4c3d-a169-7ba420ad5e15",
    "oxton-padel": "d7f9b060-de6c-44c4-ba9c-76a44ca131ff",
    "oxygen-padel": "c5560a67-b957-4013-98e7-64daf463251f",
    "padall-haverhill": "037b1c61-6f1c-4731-9367-2149e41e4141",
    "padel-16": "fcfe1ced-41fd-4d21-b4cb-7c0521a72665",
    "padel-18": "02298856-98b5-4fc3-b564-bf2a81b31fb5",
    "padel-500": "a8b6307a-181c-4478-9002-374eee97d860",
    "padel-54": "0e339a49-7fc6-49b0-b4b7-44165dc0a8d7",
    "padel-7-club": "8d0a1ae3-b178-41f3-96cd-aa99518c9833",
    "padel-at-cnw-golf-academy": "07185285-5fc7-4d1b-b44a-c58344112f01",
    "padel-at-cotswolds-hotel-spa": "e8f09e94-ca9f-402f-8c1a-49fa091e8a10",
    "padel-at-denham-grove": "d265b308-c4b0-4e43-914b-aa9954f69702",
    "padel-at-dunham-forest-golf-country-club": "8d30c300-199c-47b2-84d8-ef5908945896",
    "padel-at-floodbridge-farm": "4f2aa836-9427-4178-ac5b-f85ce59605dc",
    "padel-at-hartford-golf": "f9974b53-3c23-4157-b023-3b8ca39a5ee2",
    "padel-at-housedean": "369f2359-c143-45df-a78e-6f08d56cd153",
    "padel-at-the-toolroom": "0fcd857c-ac05-467f-9fc3-4991ab109d01",
    "padel-barn-at-crieff-hydro": "8cb1cdba-cee7-493c-a67c-4fdb19124ee3",
    "padel-bonito": "86ae97fd-b2c2-49f6-b511-7e1e97f289f4",
    "padel-boutique": "861b97eb-a18f-4930-a7cf-7ef4c9b4c163",
    "padel-central-partington": "c7ba711b-fc3c-400e-90c6-084d72e22584",
    "padel-chippenham": "0844b599-e79f-4ac5-83aa-a2b9d68e47e0",
    "padel-club-at-mytton": "278299a7-0bbb-4d72-ba0d-662f288d48b3",
    "padel-co": "a1453529-6046-4e7d-a77e-23046bf78842",
    "padel-court-club-newcastle": "3977c2b5-a86f-4a01-a9bb-17c37647d837",
    "padel-district-waltham-abbey": "5ccd5197-0083-411e-9e7f-de0a418c5b69",
    "padel-elite": "689d7cf8-1104-46b1-86c0-748c1f093cbd",
    "padel-inn-oldham": "e247e6fd-959e-479c-b64a-b8779dfcce8f",
    "padel-maidenhead": "2083cefd-b6a3-4bf9-b2a7-28a6ac704e25",
    "padel-master-doncaster": "eb0bce80-190c-4ea2-b967-ec9cc0106f8f",
    "padel-mk-milton-keynes": "e3acec99-d2e8-40bc-802e-afedaac78392",
    "padel-newark": "0aef2df3-1f73-43f3-a4d8-b07dc231dc7a",
    "padel-on-the-hill": "7d5cd08f-826f-4cf3-bdc7-e243db423f37",
    "padel-on-the-park": "8324bd81-1de0-4afa-970e-87ba581e4c64",
    "padel-padel-eltham": "60baf499-42ac-4dc6-8a55-4226a50697d2",
    "padel-pass-harpenden": "68df708a-501d-47ab-a3c2-c3547d4cb013",
    "padel-pass-luton": "c7554948-a4da-44dd-bb1c-86e8497e03b7",
    "padel-people-basingstoke": "ec4aa02a-15a6-4dad-b49b-dd75178f2eec",
    "padel-people-boston": "ae1d9547-c095-4932-8a0a-2c097946cae9",
    "padel-people-corsham": "2d7685dc-cbb2-40ae-8fb9-13d4e73b2e00",
    "padel-people-cricklade": "94b9a609-fbba-48b4-8c23-3a12fea9a923",
    "padel-people-sedlescombe": "0d841fc6-684d-4e9c-a502-a776014bdaf4",
    "padel-people-wimbledon": "4256b5d8-8d35-45bb-8c6d-e425afe94692",
    "padel-people-wimbourne": "3963c26e-1aac-4875-b014-944b574f4bf2",
    "padel-play-stratford-upon-avon": "8d6c55bf-457f-4975-a070-e022afc1ffe3",
    "padel-play-telford": "3c72e627-caa1-40c1-8382-49c196bd0041",
    "padel-play-worcester": "1025efc8-e777-4a9d-84d1-585daa8bafb3",
    "padel-powerhouse-burnham": "4d95d6f6-09a7-4e44-9291-f7ddc5b5624c",
    "padel-powerhouse-chesham": "b886b56b-1fde-4aab-89c2-6d836dcfaff7",
    "padel-republic": "01a87029-00a1-47f9-afb9-ef964c6170bb",
    "padel-rush-burton": "8494f61a-0f44-4696-9558-3247f0e8d780",
    "padel-shed-thirsk": "52f1102b-ab3c-4b36-8f01-91a4b2b9bc08",
    "padel-sheds-chester": "f4d88c7e-c349-46a9-bc50-ac01f7095a9a",
    "padel-social-club-earls-court": "1c97a3d1-ded7-4c4b-808e-8c37bb1b2a1f",
    "padel-social-club-the-o2": "9e79c4f9-3c2e-4fb8-a01f-ae514dc7e351",
    "padel-social-house": "9ce18ad4-f5b7-49cc-a0f9-2ccd48a8d496",
    "padel-squared": "7a7a1b62-1605-401e-a3f1-4fc55ab17d4f",
    "padel-studios-coventry": "5ca429ea-1e4e-4a46-920f-c3f21163a97c",
    "padel-tide-falmouth": "d287a1b5-126c-4527-82d0-fc822897356e",
    "padel-tree-harlow": "61cc76d9-45f3-495d-babd-516d3917d2b2",
    "padel-tree-hertfordshire": "0bbb54f0-8fa1-40a0-bf08-c2d821d2aab3",
    "padel-tree-peterborough": "ca670ec8-6cc7-41c1-9a2d-02aa37099922",
    "padel-tree-sutton-coldfield": "72433991-84aa-461c-8f10-59d47dd0c335",
    "padel-tree-whyteleafe": "3605b3f0-7987-40e6-81b9-53e08351c089",
    "padel-united-colchester": "c4704263-df22-468b-aeb6-ac5d1564ab36",
    "padel-united-dunmow": "e4e05642-91f0-42df-b088-f477c149cb3a",
    "padel-united-maldon": "ce373072-7575-4648-bb54-be40750796ba",
    "padel-united-plymouth": "b6271cdf-afe3-4956-86d5-e0975b45ff9c",
    "padel-united-saffron-walden": "5bc310cb-5961-4b2b-bf41-956727465fc6",
    "padel-united-stansted": "c2a85ce3-ec67-4f8d-a258-02ab25728c7b",
    "padel-united-the-wirral": "32109337-5db6-4b2a-b95f-07c3db54e625",
    "padel-united-torquay": "821e1bba-1e42-4825-a798-e7aa1249e306",
    "padel-up-knaresborough": "8a5c6a04-3326-4a99-8e63-b12ae1092dfb",
    "padel-up-mansfield": "6383e35e-fa9f-4fcb-8ae5-fdfd9d74d227",
    "padel-up-teesside": "e9a27b55-6133-44a8-865f-179bc9539b55",
    "padel-up-tyneside": "ee95d1af-5772-4ad7-8a9e-5666260ed390",
    "padel-warehouse-52": "dd7e3ef7-c45b-431b-b87c-163bfe2c8d5c",
    "padel-warehouse-52-tamworth": "37f0aeb9-8294-4581-8ed6-0a43203fe5d4",
    "padel-world-uk": "d0f59165-f8c1-4379-9e61-87c09cfd2887",
    "padel-xero-cannock": "b01ae613-ec8d-45ac-91e7-249e412b93b6",
    "padel-zest": "87cb3f01-c420-4ef5-b05a-cea4270962b9",
    "padelheim": "2a56b62a-d458-4a56-a9ce-0fdf66b10549",
    "padelhub-bs5-bristol": "6a5c7e43-29f2-42e9-8021-b3d2630f4df1",
    "padelhub-kt19-epsom": "04dd6b80-e488-4af3-b740-78704af847ef",
    "padelpriv": "8f19617d-fd7d-4889-9590-aff42cfe000b",
    "padels-up": "7221a838-8a91-469f-bbcd-72b7d99d7385",
    "padelsphere": "e6bb3ffb-adfc-4d37-8173-7823ce9dc8a5",
    "padelstars-egham": "f27edc81-e439-4c3f-82bb-8fbea4eb25a5",
    "padelstars-stratford-upon-avon": "19ecab8c-9325-4584-b533-c563fcb44bd4",
    "park-padel-sports-club": "cfd7cedc-3c93-4bf3-a382-5fc03462b500",
    "park-view-padel": "a59ede24-1966-4bc4-bdc6-7be196d9cc2a",
    "peak-district-padel": "f1cfba0d-8f3f-4690-8c49-a8c7c45fbb44",
    "peak-padel-holmfirth": "f3a2fa43-7368-46a1-bde6-2300d1cc80e4",
    "pembrokeshire-padel": "7a336313-840d-4fba-b4bd-f220855164a0",
    "pendle-padel-club": "c186526d-b572-4475-83eb-52c71a572bda",
    "performance-padel": "e1118827-6e5c-4b5c-ac86-e4d204a5294b",
    "performance-padel-kendal": "5b1d4182-99c3-4fbe-802d-2c99aa5918b8",
    "picklepad-by-smeda-sports-ltd": "983df710-093e-4839-b3c7-2ce68cf46f93",
    "pickwick-cricket-padel-club": "f582c114-a29a-42ff-b27b-7d9baa4212ce",
    "pig-pen-padel": "8467cbc1-7026-43bd-9e13-e7651ab861d6",
    "pikuppadel": "8c39c0bd-cce0-4fa0-aa69-4bba00f70d6d",
    "pine-ridge-golf-club": "7ce31bab-07b9-4777-9cff-d61423998595",
    "platform-padel-amble": "e688a204-838d-4c1c-8664-24c2ffec061e",
    "play-padel-club-deal": "abe8c96f-df91-4673-a75f-a4a755dadbe9",
    "play-padel-grendon": "e61e0bcf-de4e-4bbe-a724-cb5d6742acdc",
    "play-padel-sheffield": "9e22e957-fffb-4509-a3cd-8ada63d8a10d",
    "play-pdl": "c85d42cc-d7fd-45d8-8a88-d7af4c2039a7",
    "pontyclun-padel": "6c4212ba-d08f-4515-8d1d-5aefeab19ee9",
    "pop-up-padel-trevear-farm": "b54fed17-bb65-4670-b7bd-af04670102ff",
    "poplars-padel": "cae31eeb-8c44-4c94-a243-cda33bd7509a",
    "porthcawl-padel": "5c57afa6-f00e-4a5a-b556-ae84f09b66fe",
    "poulton-padel-club": "be28bf16-d10c-42d1-b1e4-56d6522f5622",
    "powerhouse-padel": "7148eef5-c629-4992-8fc3-6030a900f2d5",
    "powerleague-birmingham": "3d893ef8-42ac-4835-8101-dbc329598f69",
    "powerleague-bolton": "32aecb65-d5d1-411b-bcbe-5a9dfa625a22",
    "powerleague-gateshead": "e159ef30-155a-4091-91ad-14ac97f8e310",
    "powerleague-mill-hill": "12338c4b-e078-4b3a-a50e-5568293183b3",
    "powerleague-milton-keynes": "55269de1-2357-46f6-9ec3-59b0edd9c6dc",
    "powerleague-paisley": "acf3e4a9-4136-4a1e-9829-730a4709abb2",
    "powerleague-portobello": "b3250997-600d-4c21-9a27-e7f6f3f78cdf",
    "powerleague-shoreditch": "2ab75436-9bb0-4e9c-9a6f-b12931a9ca4a",
    "powerleague-sighthill": "6106e15a-01c1-40d5-991a-8dd24a04d5a1",
    "powerleague-stoke-trentham-lakes": "de9f694e-6db4-4b4d-8add-49fbfe4ed0a7",
    "prees-cricket-and-recreation-club": "6804f2de-d174-49a5-b4c2-044dba3125f9",
    "prested-hall-health-club": "f517897c-3c0d-4d7c-86c7-c125f9d083fe",
    "project-padel-newcastle": "be103486-61ba-42fa-b440-7d410e9538f3",
    "pukka-padel-leeds": "745c6912-4914-45af-bda6-e8daf367aada",
    "pukkaa-padel-kidderminster": "ce2018c2-70a1-4015-8f58-d6fc6cf3b28e",
    "pure-padel-alderley-park": "078efe1d-26d9-4c70-9a89-d397e3c5c563",
    "pure-padel-darlington": "9fb4fa6c-423c-4688-bcc0-c134a3aefef7",
    "pure-padel-lightwater": "74909723-bcd9-4184-afbc-8244fdee1de5",
    "pure-padel-manchester": "0c489d33-19e1-495e-8cd2-59d9f1e42a24",
    "pure-padel-north-leeds": "1bb5a827-1dca-440c-88be-a4751903ab3d",
    "pure-padel-nottingham": "a7aea578-a29b-406b-b7fc-238444e2f666",
    "pure-padel-solihull": "b17450c7-fa89-40be-b158-587b48a9a2bd",
    "pure-padel-stockport": "1e515061-33a8-4d15-b818-c6d3af8bfa34",
    "pure-padel-york": "ae8feb3b-df9b-412c-a273-3102bdf31f78",
    "pure-swansea": "27fe83c1-35d5-47bb-9974-c8e2e2b20181",
    "purple-padel-club": "ab8eeb3e-078a-4ee2-8494-5d5bb0786b73",
    "quik-padel": "b4bd0a7d-6553-4e2c-97f7-e8f8a2915939",
    "racquet-club-24": "6a8ba427-c3c3-418d-80c9-d23ca452302b",
    "rally-yard": "10c7b9db-e84f-4db5-b664-90384e4aa1b3",
    "revolution-padel": "a975e6a8-8c52-47e8-ac6d-1d0c403c2440",
    "rhosneigr-sports-club": "6d4be33e-e294-45ae-9410-671d3d0b4092",
    "richmond-community-sport": "1a4de0bb-34d8-43d0-b1d0-6098c1dc3b54",
    "ripon-tennis-centre": "c4cb2db3-7b15-485a-8f61-7fb74b2050d6",
    "rocks-lane-barnes-london": "e2ec82b3-3862-4e42-90bb-bb41f59e737d",
    "rocks-lane-chiswick": "9c95ac87-5273-47a9-bf67-342c566caf79",
    "rocks-lane-dyrham-park-country-club": "e24d075d-b5a5-4a0d-a303-2c7e92d9e598",
    "rocks-lane-trevose-golf-country-club": "647e7faa-2a01-4d92-8bd8-a1e041bd3dea",
    "rulo-clubs": "1b0fa0b0-8e4a-42b0-92a0-b6ea026e48ac",
    "rustons-sports-ltd": "2189eb18-6a59-4170-a676-f14322d8088b",
    "s3-padel-derby": "f0560c52-c94a-42dd-972b-9b0e755c4efc",
    "salus-padel": "fd0a3113-b9a0-4ad7-a480-4acf84ff362f",
    "sandbach-padel-club": "39d76f3d-c304-470c-b4ba-e95d38c07e04",
    "selby-padel-club": "f51b0351-8819-4af0-8c4f-631b1fcd8867",
    "shelby-farm-padel": "2558e845-8a45-4f00-95b9-c082ed2d0e3b",
    "skegness-padel": "1ae39cc6-d811-4f5b-9ad2-d8a8a0ea73f4",
    "skill-school-hq": "2aec2d13-73c6-4e02-990c-cb83c8fff25c",
    "skipton-tennis-centre": "d41c866d-8e7a-41c5-bf58-8b71bbbf0b5e",
    "slazenger-padel-clubs-blackburn": "bd55eedd-5e76-475e-8d48-9a904c1be2f3",
    "slazenger-padel-clubs-exeter": "c56d04bc-ad1f-475d-b44d-1211826a598f",
    "slazenger-padel-clubs-leeds": "71819100-f453-4ff9-8de1-55a22dd91e50",
    "soul-padel-braehead": "6bab9a63-12c9-4791-a872-877500f41569",
    "soul-padel-stockport": "5a6c0fc0-e003-4ee8-a478-1bfb0ae8581d",
    "spa-padel": "41fc8202-80ef-4c07-a9bd-5572331acffd",
    "square-one-maidstone": "87006ea9-154b-4845-82d7-f89414bee839",
    "square-one-sittingbourne": "5e3e56b1-6422-41a2-b6eb-979744e0054f",
    "star-padel-bordon": "94f5675e-231b-4f29-83bc-efc9179e4737",
    "stay-padel": "0facd69e-8d76-4857-bfb7-4dafdb21b819",
    "stewkley-tennis-padel-club": "9b200744-5b25-4064-aa63-0cd2ecae1f74",
    "strike-padel": "6a854293-2156-410c-b8fe-a57abf8dc62d",
    "surge-padel-bristol": "0709653c-712d-4863-acd4-f690a3c179f1",
    "surge-padel-harrogate": "18fda907-f989-4d40-b124-b8bf98ecbbd2",
    "tc60-padel": "ad6ab49e-c404-41c6-9f6e-8d9909384fc3",
    "te-amo-padel-at-the-hayes": "65a78678-e0ab-41ca-bff3-87b66e1c0286",
    "tennis-world-middlesbrough": "4aa4b11e-b0eb-470c-bf80-bf4e41a08095",
    "that-padel-club": "380bd59a-833c-428c-85e4-d612c468e002",
    "that-padel-club-tuxford": "8cca4c31-22bf-4712-868f-dc0998254cd2",
    "the-atrium-health-club": "f2c9b1cb-3cc8-48a2-856d-964b1c39e222",
    "the-essex-golf-and-country-club": "cd8ccdec-0624-40c3-a5ac-5b2f03ed2a26",
    "the-hay-barn-padel": "5deade72-25fb-45d5-97c2-e49982e78dff",
    "the-hook-club-at-mottram-hall": "94c140b5-964f-45f1-8900-60faf7fbb3fc",
    "the-leisure-box": "23a3ba07-6ae1-4010-83c5-3b2432fb4414",
    "the-northern-padel-house": "c045ca98-de16-4942-91cb-99cf2b0fde3b",
    "the-padel-barn": "8e05bd8f-0e00-4524-8a90-1231e9133811",
    "the-padel-barn-leeming-bar": "cc687688-049d-49a2-97e8-325f1919970a",
    "the-padel-barn-round-meadows-farm": "216b0acf-8736-4ca3-9da6-e91c3dc0157e",
    "the-padel-casa": "dffd5971-e8ba-4eba-819f-df012e76c3b5",
    "the-padel-club-at-the-mount-golf-and-country-club": "75e2c5dd-f598-477b-9ecc-b9c7b0dbe870",
    "the-padel-club-cheltenham": "dbcf1573-b557-4449-8602-8a6bb73cb765",
    "the-padel-club-chester": "086055b2-3e08-4606-b7ae-d22ed057c5cf",
    "the-padel-club-gloucester-quays": "f8922a78-29ed-4a9b-821f-8def4184294b",
    "the-padel-club-handforth-dean": "3b481e6c-feac-447c-b530-c93c24db85c0",
    "the-padel-club-traffordcity": "525217d1-035b-4a25-92c1-1b9eabf15de9",
    "the-padel-club-wilmslow": "c1b6a3e4-3528-42fd-8b24-4b5ecfec947c",
    "the-padel-farm-york": "4752279d-c7c6-4e6e-ae90-addfc4f6a891",
    "the-padel-hanger": "67800469-27e0-4bf4-b198-64ba38baaab9",
    "the-padel-hub-gu52-fleet": "62316f10-7615-47ee-825a-1b43e6c3b2e2",
    "the-padel-hub-rg1-reading": "c7a63185-4474-45b1-97bd-a930d6cf4381",
    "the-padel-hub-rh17-crawley": "b505b163-8180-4b58-a9b4-1080245a0eb7",
    "the-padel-hub-sl2-slough": "41062339-4a0c-4167-8593-f3dc861fb415",
    "the-padel-hub-so16-southampton": "ea27a502-a158-4079-8681-63bd6d091f45",
    "the-padel-hub-tunbridge-wells": "36ca1e9e-1a73-40b8-ab16-525934e3a27d",
    "the-padel-inn": "d9c9ff9d-fd9e-44bb-bead-360e09da4799",
    "the-padel-shed-selby": "b41aa012-adcf-4092-bd31-90116676678b",
    "the-padel-spot": "cfda6891-025f-4bf2-9e4b-294ad7e7ed5b",
    "the-padel-team": "f4676d1c-0f9f-4871-92cf-ef4e08a8c2d3",
    "the-padel-unit": "0e8d1263-16f3-4dce-86b4-365dd2d69018",
    "the-point-at-polzeath-with-rocks-lane": "3f2c7805-d53a-45ce-bb60-caf4f2e57c83",
    "the-pollen-club": "a606f84e-65c1-402a-a6b5-f5fe0e3d42a1",
    "the-rally-hub": "58dbb0cd-4473-4a74-9914-286510485bb6",
    "the-ranch-padel": "76e3e129-2d08-4ded-9bd5-c34f55356b8f",
    "the-shed-chidham": "7c8742ea-217e-4f3f-9b60-a7529887544b",
    "the-tytherington-club": "d6056582-6471-42ed-b894-b16eda239732",
    "the-yard-padel": "560f8fcb-663b-4a98-836e-edda51ca591f",
    "this-is-padel-dronfield": "b4f46e3d-5415-4bb8-8c42-a0825cb5365c",
    "tilney-padel": "c5a8ba91-12d2-4e84-a93e-fa4fce7ed87b",
    "tilsworth-padel-club": "6c3f87b5-86cc-4147-a09d-7680d40e187a",
    "torquay-tennis-club": "86edc80d-da83-4ba9-afb0-af5b0a6ced4b",
    "tour-padel-avery-hill-campus": "df114d7a-6bf3-427d-8d7a-d4e88865efda",
    "tour-padel-medway-campus": "b8b7e62e-210e-4aa1-a9ce-450eaae16f60",
    "true-padel-durham": "fa2f222a-a793-42fa-8356-af20e37db45d",
    "true-padel-sunderland": "3ca30199-7e76-4ce1-ae6b-d451d342d673",
    "trumpington-padel": "74e35acf-1447-403b-879a-48aab20e0b7e",
    "uno-padel-club": "469310a3-7532-42d8-adf7-05074986ba4c",
    "velocity-padel": "7accff8b-4ac5-4fd2-b6be-3485adc5bb11",
    "velocity-padel-wigan": "64bbf7d1-6850-4c18-a6e5-8eed717274cb",
    "vibora-liverpool": "7a7a6dfc-a0fc-4ee4-9807-d010f5396f28",
    "vida-del-padel": "ae63c414-9c97-4f64-8179-7ec4b8dcd7c9",
    "vida-del-padel-chichester": "c0eacdc4-f75c-47e5-98b2-b218839df40b",
    "vida-del-padel-eston": "7847761d-123a-47c7-b004-17b7cd622d82",
    "vida-del-padel-guisborough": "6352f99f-e839-4cb8-9e6c-ab5ef561bad1",
    "vida-del-padel-hartlepool": "19a39899-a426-43e9-8fa6-c174e681b8fa",
    "vida-del-padel-hull": "e6ce93ab-4849-4503-b1ac-f2c07382fd6c",
    "vida-del-padel-sheffield": "d2d4e7a2-0e85-4a6e-9c83-597e1b93bc1d",
    "village-health-wellness-club-newcastle": "f00858fd-256c-41ef-b976-f24de252ac1a",
    "vip-padel-newton-le-willows": "f548beac-64a3-4004-ba6b-6b94d517598d",
    "volt-padel": "f3cf8742-d2c7-4c53-8361-79299af7b60e",
    "volt-padel-club": "3f36ca37-d60e-4875-9271-ed10af2ddc25",
    "wadswick-padel": "e66243c8-5243-4fe4-883b-7beabc51d1c6",
    "wakefield-sports-padel-club": "202184e9-7113-4bb5-bed2-d554919de8ac",
    "weplay-padel": "af0acf02-2f2f-4350-a4c9-b3d235a56e59",
    "west-derby-padel": "03d83c77-826c-4ae9-bfae-9fdeca36f747",
    "wetherby-padel-club": "d009033b-b7ff-4a4a-a935-36b2561fbd6f",
    "widnes-padel-club": "9992884b-35d0-4add-9f03-ec13fa2d1492",
    "wigan-sports-club": "7b37e87d-5f96-4c3e-9514-c3cb5048a22d",
    "windsor-tennis-club-belfast": "c3e428e0-9536-4110-9063-287c933a1fb2",
    "wold-padel": "f29891a3-2148-4f46-9e72-cd6686ae2928",
    "wombourne-padel": "2d039433-7429-49c4-94bd-b1ab6e29c60d",
    "woodbury-park": "a0d5ffc6-67cf-461e-bdc9-490c753a041a",
    "woodby-padel": "f9f32f51-97a5-4a26-bdd8-43bfc07ade1d",
    "wressle-grange-padel-club": "5f5f4aa5-b55e-4892-8746-2547cce18019",
    "wrexham-tennis-padel-centre": "5d3685f6-4981-4b4e-9057-8ff5ddf69684",
    "york-st-john-university-padel": "b350ce06-74f6-47ab-a15e-5eaf7951e2c0",
    "yorkshire-barns": "507488a4-e111-411a-b2fb-9757327d54c2",
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
    resource_indoor_map: Optional[Dict[str, bool]] = None,
) -> List[UnifiedParserSchema]:
    """Aggregate availability across courts into one record per
    (start_time, duration, indoor). `indoor` is part of the grouping key, not
    just an extra column - a venue can have both indoor and outdoor courts
    (confirmed live, e.g. Kensington Pickleball Club), and merging their
    `spaces` counts together would make the indoor/outdoor split unfilterable
    and silently misreport which courts are actually available."""
    resource_indoor_map = resource_indoor_map or {}
    slot_map: Dict[tuple, List[str]] = defaultdict(list)

    for resource in resources:
        indoor = resource_indoor_map.get(resource.resource_id)
        for slot in resource.slots:
            slot_map[(slot.start_time, slot.duration, indoor)].append(slot.price)

    results: List[UnifiedParserSchema] = []
    for (start_time_str, duration_min, indoor), prices in slot_map.items():
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
                indoor=indoor,
            )
        )

    return results


# Strips the backslash-escaping the club page's embedded JSON carries when
# nested inside a JS string literal (confirmed live: the raw response has
# literal `\"resourceId\"` etc, not `"resourceId"`), then matches the plain
# {"resourceId":...,"name":...,"sport":...,"features":[...]} shape directly -
# same "normalise then regex" pattern as Places Leisure's schedule scrape.
_RESOURCE_FEATURES_PATTERN = re.compile(
    r'"resourceId":"([^"]+)","name":"[^"]*","sport":"[^"]*","features":\[([^\]]*)\]'
)

# venue.slug -> {resource_id: indoor bool}, populated once per slug and
# reused across every date that venue is crawled for (this is static
# facility metadata, not availability - refetching it per date would be
# hundreds of wasted requests per venue over a multi-week crawl window).
_resource_indoor_cache: Dict[str, Dict[str, bool]] = {}
_resource_indoor_cache_locks: Dict[str, asyncio.Lock] = {}


async def _fetch_resource_indoor_map(slug: str) -> Dict[str, bool]:
    """Fetch and cache {resource_id: indoor} for one venue's public club page.

    Returns {} (not raising) on any failure - callers already handle a
    resource missing from the map as "indoor unknown" via .get(), so a failed
    fetch just means this run's availability rows have indoor=None for that
    venue rather than blocking the crawl."""
    if slug in _resource_indoor_cache:
        return _resource_indoor_cache[slug]
    lock = _resource_indoor_cache_locks.setdefault(slug, asyncio.Lock())
    async with lock:
        if slug in _resource_indoor_cache:  # populated while we waited for the lock
            return _resource_indoor_cache[slug]
        try:
            async with CurlAsyncSession() as session:
                resp = await session.get(
                    f"{PLAYTOMIC_ORGANISATION_WEBSITE}/clubs/{slug}",
                    headers=_HEADERS,
                    impersonate=next_impersonate_profile(),
                    timeout=20,
                )
            content = resp.text.replace("\\", "")
            result = {}
            for resource_id, features_raw in _RESOURCE_FEATURES_PATTERN.findall(content):
                features = features_raw.lower()
                if "indoor" in features:
                    result[resource_id] = True
                elif "outdoor" in features:
                    result[resource_id] = False
            _resource_indoor_cache[slug] = result
            return result
        except Exception as exc:
            logging.warning(f"Playtomic: failed to fetch indoor/outdoor metadata for {slug}: {exc}")
            _resource_indoor_cache[slug] = {}
            return {}


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
            resource_indoor_map = await _fetch_resource_indoor_map(venue.slug)
            slots = _resources_to_unified(
                resources,
                venue,
                fetch_date,
                category=self.category,
                resource_indoor_map=resource_indoor_map,
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
