"""
Matchi strategy implementations.

For each known venue slug the crawler fetches GET /facilities/{slug}?date={date}&sport=5
directly, avoiding the deprecated POST /book/findFacilities discovery endpoint.
Slugs are stable and sourced from venues.json via the DB — no runtime discovery needed.

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
from sportscanner.crawlers.parsers.matchi.core.schema import MatchiSlot
from sportscanner.logger import logging

MATCHI_ORGANISATION_WEBSITE = "https://www.matchi.se"
LONDON_TZ = ZoneInfo("Europe/London")
PADEL_SPORT_ID = 5


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
    """Stub — Matchi crawler bypasses the standard per-venue request loop."""

    @override
    def generate_request_details(
        self,
        sports_venue: sportscanner.storage.postgres.tables.SportsVenue,
        fetch_date: date,
        token: Optional[str] = None,
    ) -> List[RequestDetailsWithMetadata]:
        return [
            RequestDetailsWithMetadata(
                url=f"{MATCHI_ORGANISATION_WEBSITE}/facilities/{sports_venue.slug}",
                headers={},
                payload=None,
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
        """Crawl availability for a single date across all known Matchi slugs concurrently."""
        slot_lists = await asyncio.gather(
            *[self._fetch_facility_slots(client, slug, fetch_date) for slug in venue_by_slug],
            return_exceptions=True,
        )

        matchi_slots: List[MatchiSlot] = []
        for r in slot_lists:
            if isinstance(r, Exception):
                logging.error(f"Matchi facility task raised: {r}")
            elif r:
                matchi_slots.extend(r)

        logging.info(f"Matchi: {len(matchi_slots)} slot groups for {fetch_date}")
        if not matchi_slots:
            return []

        results: List[UnifiedParserSchema] = []
        for ms in matchi_slots:
            record = self._to_unified(ms, venue_by_slug, fetch_date)
            if record:
                results.append(record)

        logging.success(f"Matchi: {len(results)} records built for {fetch_date}")
        return results

    # -- internal helpers -----------------------------------------------------

    async def _fetch_facility_slots(
        self, client: httpx.AsyncClient, slug: str, fetch_date: date
    ) -> List[MatchiSlot]:
        """Fetch and parse availability for one facility on one date."""
        url = f"{MATCHI_ORGANISATION_WEBSITE}/facilities/{slug}"
        try:
            resp = await client.get(
                url,
                params={"date": fetch_date.isoformat(), "sport": PADEL_SPORT_ID},
                timeout=30,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logging.error(f"Matchi {slug} HTTP {exc.response.status_code} for {fetch_date}")
            return []
        except Exception as exc:
            logging.error(f"Matchi {slug} failed for {fetch_date}: {exc}")
            return []

        slots, _ = _parse_html_page(resp.text)
        logging.debug(f"Matchi: {slug} {fetch_date} → {len(slots)} slot groups")
        return slots

    def _to_unified(
        self,
        ms: MatchiSlot,
        venue_by_slug: Dict[str, sportscanner.storage.postgres.tables.SportsVenue],
        search_date: date,
    ) -> Optional[UnifiedParserSchema]:
        venue = venue_by_slug.get(ms.facility_slug)
        if not venue:
            return None

        return UnifiedParserSchema(
            category="Padel",
            starting_time=_ms_to_london_time(ms.start_timestamp_ms),
            ending_time=_ms_to_london_time(ms.end_timestamp_ms),
            date=search_date,
            price="£55.00",
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
