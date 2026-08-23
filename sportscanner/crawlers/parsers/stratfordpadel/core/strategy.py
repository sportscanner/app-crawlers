import re
from datetime import datetime, time as time_cls, date as date_cls
from typing import List, Optional, Tuple

import httpx

from sportscanner.crawlers.parsers.core.schemas import RawResponseData
from sportscanner.crawlers.parsers.core.interfaces import AbstractResponseParserStrategy
from sportscanner.crawlers.helpers import override

from sportscanner.logger import logging

from sportscanner.crawlers.parsers.stratfordpadel.core.schema import (
    StratfordPadelCuadroResponse,
)
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema

GRID_URL = "https://stratfordpadelclub.matchpoint.com.es/Booking/Grid.aspx"
OBTENER_CUADRO_URL = (
    "https://stratfordpadelclub.matchpoint.com.es/booking/srvc.aspx/ObtenerCuadro"
)
BOOKING_URL = "https://stratfordpadelclub.matchpoint.com.es/Booking/Grid.aspx"
# Grid cuadro id 4 is the one whose Nombre is "Padel" (ids 5 and 7 exist on this
# tenant but are not the padel availability grid).
ID_CUADRO = 4
# The anti-CSRF "key" global is injected into Grid.aspx markup with an obfuscated
# variable name. It rotates on every page load and must be echoed back by each
# srvc.aspx page-method call.
SESSION_KEY_PATTERN = re.compile(r"hl90njda2b89k='([^']+)'")
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": GRID_URL,
    "X-Requested-With": "XMLHttpRequest",
}


async def fetch_session_key_and_cookies(
    client: httpx.AsyncClient,
) -> Optional[str]:
    """Phase 1 of the two-phase WebForms handshake: GET the grid page
    anonymously to establish the ASP.NET session cookie and harvest the
    per-page-load key that srvc.aspx page methods require. Returns None when
    the key cannot be found (page shape changed)."""
    response = await client.get(
        GRID_URL, headers={**BROWSER_HEADERS, "Accept": "text/html"}
    )
    response.raise_for_status()
    match = SESSION_KEY_PATTERN.search(response.text)
    if not match:
        logging.error(
            "Stratford Padel: session key pattern not found in Grid.aspx - page "
            "structure may have changed"
        )
        return None
    return match.group(1)


async def fetch_cuadro_raw(
    client: httpx.AsyncClient, session_key: str, fetch_date: date_cls
) -> dict:
    """Phase 2: POST ObtenerCuadro for one date. Dates use UK format dd/MM/yyyy
    (the centre's culture is es-ES with ShortDatePattern dd/MM/yyyy); ISO
    yyyy-MM-dd is silently ignored and returns an empty cuadro. ASP.NET page
    methods answer with a {"d": <payload>} envelope."""
    payload = {
        "idCuadro": ID_CUADRO,
        "fecha": fetch_date.strftime("%d/%m/%Y"),
        "key": session_key,
    }
    response = await client.post(
        OBTENER_CUADRO_URL, json=payload, headers=BROWSER_HEADERS
    )
    response.raise_for_status()
    body = response.json()
    return body.get("d") or {}


def _parse_hhmm(value: Optional[str]) -> Optional[time_cls]:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError:
        return None


def _free_intervals_within_opening_hours(
    opening: Optional[time_cls],
    closing: Optional[time_cls],
    ocupaciones: List[Tuple[time_cls, time_cls]],
) -> List[Tuple[time_cls, time_cls]]:
    """Complement of the booked blocks inside [opening, closing]. The club's
    day is tiled by bookings in 30-minute-aligned blocks, so each maximal free
    interval is exactly one genuinely bookable window."""
    if opening is None or closing is None or opening >= closing:
        return []
    ordered = sorted(ocupaciones)
    free: List[Tuple[time_cls, time_cls]] = []
    cursor = opening
    for start, end in ordered:
        if end <= cursor or start >= closing:
            continue
        start_clamped = max(start, cursor)
        if start_clamped > cursor:
            free.append((cursor, start_clamped))
        cursor = max(cursor, min(end, closing))
        if cursor >= closing:
            break
    if cursor < closing:
        free.append((cursor, closing))
    return free


class StratfordPadelResponseParserStrategy(AbstractResponseParserStrategy):
    """Turns one ObtenerCuadro payload into UnifiedParserSchema rows.

    Modelling of the Busy/Open legend:
      - every occupancy block on a court -> one row with spaces=0 (busy), same
        convention as Better/UEL which emit fully-booked slots too;
      - the complement gaps between bookings within opening hours -> one row
        per maximal free interval with spaces=1 (open, pay-and-play).

    No prices are exposed to anonymous users anywhere in the API responses
    (verified live), so price is left empty."""

    def _transform_raw_response_to_typed(
        self, api_response
    ) -> StratfordPadelCuadroResponse:
        return StratfordPadelCuadroResponse(**api_response)

    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        if not raw_response.content:
            return []
        cuadro = self._transform_raw_response_to_typed(raw_response.content)
        if not cuadro.Columnas:
            return []
        slot_date: date_cls = raw_response.requestMetadata.metadata.date
        unified_schema_output: List[UnifiedParserSchema] = []
        for court in cuadro.Columnas:
            busy: List[Tuple[time_cls, time_cls]] = []
            for ocupacion in court.Ocupaciones:
                start = _parse_hhmm(ocupacion.StrHoraInicioMostrar)
                end = _parse_hhmm(ocupacion.StrHoraFinMostrar)
                if start is None or end is None or start >= end:
                    continue
                busy.append((start, end))
                unified_schema_output.append(
                    UnifiedParserSchema(
                        category=raw_response.requestMetadata.metadata.category,
                        starting_time=start,
                        ending_time=end,
                        date=slot_date,
                        price="",
                        spaces=0,
                        composite_key=raw_response.requestMetadata.metadata.sportsCentre.composite_key,
                        last_refreshed=raw_response.requestMetadata.metadata.last_refreshed,
                        booking_url=raw_response.requestMetadata.metadata.booking_url,
                    )
                )
            for start, end in _free_intervals_within_opening_hours(
                _parse_hhmm(cuadro.StrHoraInicio), _parse_hhmm(cuadro.StrHoraFin), busy
            ):
                unified_schema_output.append(
                    UnifiedParserSchema(
                        category=raw_response.requestMetadata.metadata.category,
                        starting_time=start,
                        ending_time=end,
                        date=slot_date,
                        price="",
                        spaces=1,
                        composite_key=raw_response.requestMetadata.metadata.sportsCentre.composite_key,
                        last_refreshed=raw_response.requestMetadata.metadata.last_refreshed,
                        booking_url=raw_response.requestMetadata.metadata.booking_url,
                    )
                )
        return unified_schema_output
