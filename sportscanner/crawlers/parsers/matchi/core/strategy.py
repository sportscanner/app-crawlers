"""
Matchi strategy implementations.

The crawler fetches GET /book/listSlots?facility={id}&date={date}&sport=5 for each
known venue.  This is the mobile-view AJAX endpoint — it returns HTML with the same
btn-slot / collapse-panel structure but for a single facility only.  Timestamps are
true Unix UTC milliseconds, converted to London local time via ZoneInfo.

Facility IDs (numeric) are stable DB identifiers; they are hardcoded in
SLUG_TO_FACILITY_ID alongside the slug.  When adding a new venue, look up its
facilityId from the JS on its facility page (facilityId=<n> in the inline script)
and add it to the mapping.

Time-zone note
--------------
/book/listSlots timestamps are true Unix milliseconds UTC (verified: the 07:00 BST
slot for 2026-05-22 returns 1779426000000 = 06:00 UTC → 07:00 BST).  The old
/book/findFacilities endpoint embedded Stockholm-local (CEST = UTC+2) timestamps
which caused a 1-hour lag.  ZoneInfo('Europe/London') handles BST/GMT automatically.
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
PADEL_SPORT_ID = 5

# Matchi's backend encodes UK venue slot times in Stockholm local time (CEST/CET).
# Stockholm is always UTC+1 ahead of London — extracting the Stockholm hour/minute
# directly gives the time as Matchi intends it (and as shown on the Matchi website).
_STOCKHOLM_TZ = ZoneInfo("Europe/Stockholm")

# Stable slug → numeric facility ID mapping.
# To find a facilityId: visit matchi.se/facilities/{slug} and search the inline JS for facilityId=<n>.
SLUG_TO_FACILITY_ID: Dict[str, int] = {
    "game4padelgll":              2636,
    "towerhillterrace":           2996,
    "londonbridgecity":           3041,
    "stpaulscathedralchurchyard": 2995,
    "g4pvauxhallpadelyard":       3011,
    "game4padelcrystalpalace":    2368,
    "westhertssportsclub":        3178,
    "cltc":                       2466,
    "g4pthepadelyard":            2322,
    "game4padelparkside":         2573,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ms_to_booking_time(timestamp_ms: int):
    """Extract the booking time from a Matchi UTC millisecond timestamp.

    Matchi stores UK venue slot times in Stockholm local time (CEST in summer,
    CET in winter).  The Stockholm wall-clock reading matches the time displayed
    on the Matchi website — using it directly avoids a spurious 1-hour offset
    that would occur by converting UTC → London (BST), since Stockholm is always
    UTC+1 ahead of London year-round.
    """
    dt_stockholm = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).astimezone(_STOCKHOLM_TZ)
    return dt_stockholm.time().replace(second=0, microsecond=0)


def _parse_listslots_html(html_content: str, facility_slug: str) -> List[MatchiSlot]:
    """
    Parse available slots from GET /book/listSlots response HTML.

    Structure:
      <button class="btn-slot" data-target="#facilityId_startTimestampMs"
              data-slots="[&quot;slotId&quot;, ...]">HH<sup>MM</sup></button>

      <div class="panel panel-default collapse" id="facilityId_startTimestampMs">
        ...
        <a href="...&start=startMs&end=endMs...">Book</a>
      </div>
    """
    soup = BeautifulSoup(html_content, "html.parser")
    slots: List[MatchiSlot] = []

    # Build panel-id → end_timestamp map from booking links
    panel_end_ts: Dict[str, int] = {}
    for panel in soup.select("div.panel.panel-default[id]"):
        panel_id = panel["id"]
        booking_a = panel.find("a", href=re.compile(r"end=\d+"))
        if booking_a:
            end_m = re.search(r"end=(\d+)", booking_a["href"])
            if end_m:
                panel_end_ts[panel_id] = int(end_m.group(1))

    for button in soup.select("button.btn-slot"):
        target = button.get("data-target", "").lstrip("#")
        ts_match = re.search(r"_(\d+)$", target)
        if not ts_match:
            continue
        start_ts_ms = int(ts_match.group(1))
        facility_id = target[: target.rfind("_")]

        raw_slots = button.get("data-slots", "[]")
        try:
            slot_id_list: List[str] = json.loads(html_lib.unescape(raw_slots))
        except json.JSONDecodeError:
            continue
        if not slot_id_list:
            continue

        end_ts_ms = panel_end_ts.get(target)
        duration_minutes = 90  # padel default
        if end_ts_ms is not None:
            duration_minutes = (end_ts_ms - start_ts_ms) // 60_000
        else:
            end_ts_ms = start_ts_ms + duration_minutes * 60_000

        slots.append(
            MatchiSlot(
                facility_id=facility_id,
                facility_name="",
                facility_slug=facility_slug,
                start_timestamp_ms=start_ts_ms,
                end_timestamp_ms=end_ts_ms,
                slot_ids=slot_id_list,
                duration_minutes=duration_minutes,
            )
        )

    return slots


# ---------------------------------------------------------------------------
# Strategy classes
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
                url=f"{MATCHI_ORGANISATION_WEBSITE}/book/listSlots",
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
        """Crawl availability for a single date across all known Matchi venues concurrently."""
        matched = [
            (slug, SLUG_TO_FACILITY_ID[slug])
            for slug in venue_by_slug
            if slug in SLUG_TO_FACILITY_ID
        ]
        unmatched = [slug for slug in venue_by_slug if slug not in SLUG_TO_FACILITY_ID]
        if unmatched:
            logging.warning(
                f"Matchi: {len(unmatched)} slug(s) have no facility ID — "
                f"add them to SLUG_TO_FACILITY_ID: {unmatched}"
            )

        slot_lists = await asyncio.gather(
            *[self._fetch_facility_slots(client, slug, fid, fetch_date) for slug, fid in matched],
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
        self,
        client: httpx.AsyncClient,
        slug: str,
        facility_id: int,
        fetch_date: date,
    ) -> List[MatchiSlot]:
        """Fetch available slots for one facility on one date via /book/listSlots."""
        try:
            resp = await client.get(
                f"{MATCHI_ORGANISATION_WEBSITE}/book/listSlots",
                params={
                    "wl": "",
                    "facility": facility_id,
                    "date": fetch_date.isoformat(),
                    "sport": PADEL_SPORT_ID,
                },
                timeout=30,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logging.error(f"Matchi {slug} HTTP {exc.response.status_code} for {fetch_date}")
            return []
        except Exception as exc:
            logging.error(f"Matchi {slug} failed for {fetch_date}: {exc}")
            return []

        slots = _parse_listslots_html(resp.text, slug)
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
            starting_time=_ms_to_booking_time(ms.start_timestamp_ms),
            ending_time=_ms_to_booking_time(ms.end_timestamp_ms),
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
