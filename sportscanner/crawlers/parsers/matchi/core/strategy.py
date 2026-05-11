"""
Matchi strategy implementations.

Matchi (matchi.se) serves HTML for its facility-listing endpoint and loads prices
via a separate JSON endpoint.  The crawl has two phases per date:

  1. POST /book/findFacilities  → HTML → MatchiSlot objects  (paginated)
  2. GET  /book/getSlotPrices   → JSON → price lookup by slot ID

Because one Matchi request retrieves ALL London padel venues at once (unlike the
per-venue model used by Better/GLL), we override BaseCrawler.ScraperCoroutines
in MatchiPadelCrawler to iterate over dates rather than (venue × date) pairs.
The venue list from the DB is used purely to build a slug → SportsVenue map for
composite-key resolution.

Time-zone note
--------------
Matchi timestamps are Unix milliseconds UTC.  The site renders times in CEST
(UTC+2 — Swedish HQ), but London venues must be shown in London local time
(BST = UTC+1 in summer, GMT = UTC in winter).  ZoneInfo('Europe/London') is
used so DST transitions are handled automatically.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Coroutine, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

import sportscanner.storage.postgres.tables
from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.core.interfaces import (
    AbstractAsyncTaskCreationStrategy,
    AbstractRequestStrategy,
    AbstractResponseParserStrategy,
)
from sportscanner.crawlers.parsers.core.schemas import (
    AdditionalRequestMetadata,
    RawResponseData,
    RequestDetailsWithMetadata,
    UnifiedParserSchema,
)
from sportscanner.crawlers.parsers.matchi.core.schema import MatchiPriceItem, MatchiSlot
from sportscanner.logger import logging

MATCHI_ORGANISATION_WEBSITE = "https://www.matchi.se"
LONDON_TZ = ZoneInfo("Europe/London")
PADEL_SPORT_ID = 5

# Fixed search centre used for all London padel queries
_LONDON_LAT = 51.5072
_LONDON_LNG = -0.1276
_PAGE_SIZE = 10  # Matchi returns at most 10 facilities per page


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ms_to_london_time(timestamp_ms: int):
    """Convert a Unix-millisecond UTC timestamp to a London-local time object."""
    dt_utc = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return dt_utc.astimezone(LONDON_TZ).time().replace(second=0, microsecond=0)


def _parse_html_page(html_content: str) -> tuple[List[MatchiSlot], int]:
    """
    Extract MatchiSlot objects from one page of /book/findFacilities HTML.

    Returns (slots, n_facilities) where n_facilities is the count of facility
    panels found — used for pagination (last page has < _PAGE_SIZE facilities).

    Each facility panel contains:
      • <a href="/facilities/{slug}?…"> — facility name and slug
      • <div id="slots_{facilityId}">  — facility ID
      • <button class="btn-slot"> elements with:
            data-target="#facilityId_startTimestampMs"
            data-slots="[…]"  (HTML-entity-encoded JSON array of slot IDs)
      • Collapse divs with slot-detail rows (duration, booking href → end timestamp)
    """
    soup = BeautifulSoup(html_content, "html.parser")
    slots: List[MatchiSlot] = []
    n_facilities = 0

    for panel in soup.select("div.panel.panel-default"):
        link = panel.select_one("a[href^='/facilities/']")
        if not link:
            continue
        slug_match = re.search(r"/facilities/([^?&#]+)", link.get("href", ""))
        if not slug_match:
            continue
        facility_slug = slug_match.group(1)
        facility_name = link.get_text(strip=True)

        slot_container = panel.select_one("div[id^='slots_']")
        if not slot_container:
            continue
        facility_id = slot_container["id"].replace("slots_", "")
        n_facilities += 1  # count facilities, not slot groups

        for button in panel.select("button.btn-slot"):
            target = button.get("data-target", "")
            ts_match = re.search(r"_(\d+)$", target)
            if not ts_match:
                continue
            start_ts_ms = int(ts_match.group(1))

            raw_slots = button.get("data-slots", "[]")
            try:
                slot_id_list: List[str] = json.loads(html_lib.unescape(raw_slots))
            except json.JSONDecodeError:
                continue
            if not slot_id_list:
                continue

            # Derive end timestamp + duration from the collapse detail block
            collapse_id = target.lstrip("#")
            collapse_div = panel.find("div", id=collapse_id)
            end_ts_ms: Optional[int] = None
            duration_minutes = 90  # padel default

            if collapse_div:
                booking_a = collapse_div.find("a", href=re.compile(r"end=\d+"))
                if booking_a:
                    end_m = re.search(r"end=(\d+)", booking_a["href"])
                    if end_m:
                        end_ts_ms = int(end_m.group(1))
                        duration_minutes = (end_ts_ms - start_ts_ms) // 60_000

                dur_td = collapse_div.find("td", string=re.compile(r"^\d+min$"))
                if dur_td:
                    dur_m = re.search(r"(\d+)", dur_td.get_text())
                    if dur_m:
                        duration_minutes = int(dur_m.group(1))

            if end_ts_ms is None:
                end_ts_ms = start_ts_ms + duration_minutes * 60_000

            slots.append(
                MatchiSlot(
                    facility_id=facility_id,
                    facility_name=facility_name,
                    facility_slug=facility_slug,
                    start_timestamp_ms=start_ts_ms,
                    end_timestamp_ms=end_ts_ms,
                    slot_ids=slot_id_list,
                    duration_minutes=duration_minutes,
                )
            )

    return slots, n_facilities


# ---------------------------------------------------------------------------
# Strategy classes (satisfy the abstract interface; not used via BaseCrawler)
# ---------------------------------------------------------------------------

class MatchiRequestStrategy(AbstractRequestStrategy):
    """Generates a single POST request to /book/findFacilities for a venue+date."""

    @override
    def generate_request_details(
        self,
        sports_venue: sportscanner.storage.postgres.tables.SportsVenue,
        fetch_date: date,
        token: Optional[str] = None,
    ) -> List[RequestDetailsWithMetadata]:
        return [
            RequestDetailsWithMetadata(
                url=f"{MATCHI_ORGANISATION_WEBSITE}/book/findFacilities",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "*/*",
                },
                payload={
                    "lat": _LONDON_LAT,
                    "lng": _LONDON_LNG,
                    "offset": 0,
                    "outdoors": "",
                    "sport": PADEL_SPORT_ID,
                    "date": fetch_date.isoformat(),
                    "q": "London",
                    "hasCamera": "",
                },
                metadata=AdditionalRequestMetadata(
                    category="Padel",
                    date=fetch_date,
                    sportsCentre=sports_venue,
                ),
            )
        ]


class MatchiResponseParserStrategy(AbstractResponseParserStrategy):
    """Pass-through parser: content is already List[UnifiedParserSchema]."""

    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        return raw_response.content


class MatchiTaskCreationStrategy(AbstractAsyncTaskCreationStrategy):
    """
    Not used via the standard BaseCrawler iteration — MatchiPadelCrawler calls
    crawl_date() directly.  The create_tasks_for_item stub is here only to
    satisfy the abstract interface.
    """

    # -- public API used by MatchiPadelCrawler --------------------------------

    async def crawl_date(
        self,
        client: httpx.AsyncClient,
        fetch_date: date,
        venue_by_slug: Dict[str, sportscanner.storage.postgres.tables.SportsVenue],
    ) -> List[UnifiedParserSchema]:
        """Full two-phase crawl for a single date across all London venues.

        Phase 1: paginated HTML fetch → MatchiSlot list
        Phase 2: concurrent per-slot-group price fetch via getSlotPrices
                 (one call per button/time-slot, not a global batch — the API
                 only returns prices for IDs from a single time slot at once)
        """
        matchi_slots = await self._fetch_all_slots(client, fetch_date)
        logging.info(f"Matchi: {len(matchi_slots)} slot groups for {fetch_date}")
        if not matchi_slots:
            return []

        # TODO: currently we fetch the price for only the FIRST slot group per venue and
        # reuse it for all other slots at that venue on the same date. Prices at the same
        # venue vary by time-of-day (peak/off-peak) so this may be inaccurate — revisit
        # by fetching per-slot prices once Matchi's rate limiting is better understood.
        semaphore = asyncio.Semaphore(3)
        venue_price_map: Dict[str, Dict[str, float]] = {}
        first_slot_by_venue: Dict[str, MatchiSlot] = {}
        for ms in matchi_slots:
            if ms.facility_slug not in first_slot_by_venue:
                first_slot_by_venue[ms.facility_slug] = ms

        price_tasks = [
            self._fetch_prices(ms.slot_ids, semaphore)
            for ms in first_slot_by_venue.values()
        ]
        fetched_maps = await asyncio.gather(*price_tasks)
        for slug, pm in zip(first_slot_by_venue.keys(), fetched_maps):
            venue_price_map[slug] = pm

        logging.debug(f"Matchi: prices fetched for {len(first_slot_by_venue)} venues (reused across slots)")

        results: List[UnifiedParserSchema] = []
        for ms in matchi_slots:
            pm = venue_price_map.get(ms.facility_slug, {})
            record = self._to_unified(ms, pm, venue_by_slug, fetch_date)
            if record:
                results.append(record)

        logging.success(f"Matchi: {len(results)} records built for {fetch_date}")
        return results

    # -- internal helpers -----------------------------------------------------

    async def _fetch_all_slots(
        self, client: httpx.AsyncClient, fetch_date: date
    ) -> List[MatchiSlot]:
        """Paginate /book/findFacilities until the last page."""
        all_slots: List[MatchiSlot] = []
        offset = 0
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
        }
        while True:
            payload = {
                "lat": _LONDON_LAT,
                "lng": _LONDON_LNG,
                "offset": offset,
                "outdoors": "",
                "sport": PADEL_SPORT_ID,
                "date": fetch_date.isoformat(),
                "q": "London",
                "hasCamera": "",
            }
            try:
                resp = await client.post(
                    f"{MATCHI_ORGANISATION_WEBSITE}/book/findFacilities",
                    data=payload,
                    headers=headers,
                    timeout=30,
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logging.error(f"Matchi findFacilities HTTP error (offset={offset}): {exc}")
                break
            except Exception as exc:
                logging.error(f"Matchi findFacilities failed (offset={offset}): {exc}")
                break

            page_slots, n_facilities = _parse_html_page(resp.text)
            logging.debug(f"Matchi: offset={offset} → {n_facilities} facilities, {len(page_slots)} slot groups")
            all_slots.extend(page_slots)

            if n_facilities < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        return all_slots

    async def _fetch_prices(
        self,
        slot_ids: List[str],
        semaphore: Optional[asyncio.Semaphore] = None,
    ) -> Dict[str, float]:
        """Fetch prices for the courts in ONE slot button (typically 1-3 IDs).

        Matchi's getSlotPrices only returns data when given slot IDs that all
        belong to the same time slot at the same facility.  Mixing IDs from
        different slot groups or large batches results in an empty response.

        A fresh httpx client avoids the connection-state issue that arises when
        the same client previously made the findFacilities POST.  A semaphore
        caps concurrent calls so we don't open 80+ connections simultaneously.
        """
        if not slot_ids:
            return {}
        sem = semaphore or asyncio.Semaphore(3)
        async with sem:
            for attempt in range(3):
                try:
                    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                        resp = await c.get(
                            f"{MATCHI_ORGANISATION_WEBSITE}/book/getSlotPrices",
                            params=[("slotId", sid) for sid in slot_ids],
                            follow_redirects=True,
                        )
                        if resp.status_code == 429:
                            wait = 2 ** attempt
                            logging.warning(f"Matchi getSlotPrices 429 (attempt {attempt+1}), retrying in {wait}s")
                            await asyncio.sleep(wait)
                            continue
                        resp.raise_for_status()
                        if resp.text.strip():
                            return {item["slotId"]: item["price"] for item in resp.json()}
                        return {}
                except Exception as exc:
                    logging.error(f"Matchi getSlotPrices failed for {slot_ids[:2]}: {exc}")
                    break
            return {}

    def _to_unified(
        self,
        ms: MatchiSlot,
        price_map: Dict[str, float],
        venue_by_slug: Dict[str, sportscanner.storage.postgres.tables.SportsVenue],
        search_date: date,
    ) -> Optional[UnifiedParserSchema]:
        venue = venue_by_slug.get(ms.facility_slug)
        if not venue:
            return None

        price_value = next((price_map[sid] for sid in ms.slot_ids if sid in price_map), None)
        price_str = f"£{price_value:.2f}" if price_value is not None else "N/A"

        return UnifiedParserSchema(
            category="Padel",
            starting_time=_ms_to_london_time(ms.start_timestamp_ms),
            ending_time=_ms_to_london_time(ms.end_timestamp_ms),
            date=search_date,
            price=price_str,
            spaces=len(ms.slot_ids),
            composite_key=venue.composite_key,
            last_refreshed=datetime.now(),
            booking_url=(
                f"{MATCHI_ORGANISATION_WEBSITE}/facilities/"
                f"{ms.facility_slug}?date={search_date.isoformat()}&sport={PADEL_SPORT_ID}"
            ),
        )

    # -- interface stub -------------------------------------------------------

    @override
    async def create_tasks_for_item(
        self,
        client: httpx.AsyncClient,
        sports_venue: Any,
        fetch_date: date,
        request_strategy: AbstractRequestStrategy,
        response_parser_strategy: AbstractResponseParserStrategy,
    ) -> List[Coroutine[Any, Any, List[UnifiedParserSchema]]]:
        raise NotImplementedError(
            "MatchiTaskCreationStrategy uses crawl_date(); "
            "call via MatchiPadelCrawler.ScraperCoroutines."
        )
