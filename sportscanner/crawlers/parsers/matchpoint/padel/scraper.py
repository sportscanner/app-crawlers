"""
Matchpoint (TPC-MatchPoint) padel scraper.

Reuses the Stratford Padel adapter's ASP.NET WebForms handshake and cuadro
parser, but resolves a per-tenant host + grid id from
``matchpoint/core/venues.py`` so the whole provider can be crawled in one run.
Availability is public and anonymous: a tenant is only registered here after
``/Booking/Grid.aspx`` returned its grid without redirecting to Login.aspx.
"""

from __future__ import annotations

import asyncio
import itertools
from datetime import date
from typing import Any, Coroutine, Dict, List

import httpx

from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.core.interfaces import BaseCrawler
from sportscanner.crawlers.parsers.core.fetch_failures import record_failure
from sportscanner.crawlers.parsers.core.schemas import (
    AdditionalRequestMetadata,
    RawResponseData,
    RequestDetailsWithMetadata,
    UnifiedParserSchema,
)
from sportscanner.crawlers.parsers.matchpoint.core.venues import (
    MATCHPOINT_TENANTS,
)
from sportscanner.crawlers.parsers.stratfordpadel.core.strategy import (
    BROWSER_HEADERS,
    StratfordPadelResponseParserStrategy,
    fetch_cuadro_raw,
    fetch_session_key_and_cookies,
)
from sportscanner.logger import logging
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.variables import settings

MATCHPOINT_ORGANISATION_WEBSITE = "https://tpcmatchpoint.com"


class MatchpointPadelCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(
            request_strategy=None,
            response_parser_strategy=StratfordPadelResponseParserStrategy(),
            organisation_website=MATCHPOINT_ORGANISATION_WEBSITE,
        )

    async def _fetch_date(
        self,
        client: httpx.AsyncClient,
        session_key: str,
        sports_venue: SportsVenue,
        fetch_date: date,
        host: str,
        grid_id: int,
    ) -> List[UnifiedParserSchema]:
        grid_url = f"https://{host}/Booking/Grid.aspx"
        raw_payload = await fetch_cuadro_raw(
            client,
            session_key,
            fetch_date,
            obtener_cuadro_url=f"https://{host}/booking/srvc.aspx/ObtenerCuadro",
            id_cuadro=grid_id,
            referer=grid_url,
        )
        if not isinstance(raw_payload, dict) or not raw_payload.get("Columnas"):
            logging.warning(
                f"Matchpoint({host}): empty cuadro for {fetch_date} - possibly "
                f"outside the bookable window or session expired"
            )
            return []
        request_details = RequestDetailsWithMetadata(
            url=grid_url,
            headers=BROWSER_HEADERS,
            payload={"fecha": fetch_date.strftime("%d/%m/%Y")},
            metadata=AdditionalRequestMetadata(
                category="Padel",
                date=fetch_date,
                price=None,
                booking_url=grid_url,
                sportsCentre=sports_venue,
            ),
        )
        raw_data_obj = RawResponseData(
            content=raw_payload,
            status_code=200,
            headers={},
            requestMetadata=request_details,
        )
        return self.response_parser_strategy.parse(raw_data_obj)

    @override
    def ScraperCoroutines(
        self, sports_venues: List[SportsVenue], dates: List[date]
    ) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
        return self._crawl_async(sports_venues, dates)

    async def _crawl_async(
        self, sports_venues: List[SportsVenue], dates: List[date]
    ) -> List[UnifiedParserSchema]:
        mapped = [
            (venue, MATCHPOINT_TENANTS[venue.slug])
            for venue in sports_venues
            if venue.slug in MATCHPOINT_TENANTS
        ]
        unmapped = [venue.slug for venue in sports_venues if venue.slug not in MATCHPOINT_TENANTS]
        if unmapped:
            logging.error(
                f"Matchpoint: no tenant mapping for {unmapped} - skipping these venues"
            )
        if not mapped:
            return []

        hosts = sorted({tenant["host"] for _, tenant in mapped})
        semaphore = asyncio.Semaphore(
            settings.CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER
        )
        async with httpx.AsyncClient(timeout=20) as client:
            session_keys: Dict[str, str] = {}
            for host in hosts:
                try:
                    key = await fetch_session_key_and_cookies(
                        client, grid_url=f"https://{host}/Booking/Grid.aspx"
                    )
                except Exception as e:
                    logging.error(
                        f"Matchpoint({host}): grid handshake failed: "
                        f"{type(e).__name__}: {e!r}"
                    )
                    record_failure(
                        f"Matchpoint({host}) grid handshake failed: {type(e).__name__}: {e!r}",
                        retryable=True,
                    )
                    continue
                if key:
                    session_keys[host] = key
                else:
                    logging.error(f"Matchpoint({host}): no session key - skipping")
                    record_failure(
                        f"Matchpoint({host}) no session key", retryable=True
                    )

            logging.info(
                f"Matchpoint: handshake OK for {len(session_keys)}/{len(hosts)} "
                f"tenant(s), crawling {len(mapped)} venue(s) across {len(dates)} date(s)"
            )

            async def bounded(
                venue: SportsVenue, tenant: dict, fetch_date: date
            ) -> List[UnifiedParserSchema]:
                key = session_keys.get(tenant["host"])
                if not key:
                    return []
                async with semaphore:
                    return await self._fetch_date(
                        client,
                        key,
                        venue,
                        fetch_date,
                        tenant["host"],
                        tenant["grid_id"],
                    )

            results = await asyncio.gather(
                *(
                    bounded(venue, tenant, fetch_date)
                    for (venue, tenant), fetch_date in itertools.product(mapped, dates)
                ),
                return_exceptions=True,
            )
        all_slots: List[UnifiedParserSchema] = []
        for r in results:
            if isinstance(r, Exception):
                logging.error(f"Matchpoint task raised: {r!r}")
                record_failure(f"Matchpoint task raised: {r!r}", retryable=True)
            elif r:
                all_slots.extend(r)
        return all_slots


def coroutines(search_dates: List[date]):
    """Pipeline entry point. The API enforces its own bookable window, so no
    date narrowing is applied."""
    return MatchpointPadelCrawler().coroutines(
        search_dates, sport="padel", delta=None
    )


if __name__ == "__main__":
    from rich import print

    _dates = [date.today()]
    crawler = MatchpointPadelCrawler()
    venue = SportsVenue(
        composite_key="00000000",
        organisation="Matchpoint",
        organisation_website=MATCHPOINT_ORGANISATION_WEBSITE,
        venue_name="The Heron Padel Club",
        slug="the-heron-padel-club",
        postcode="CM13 3LW",
        address="The Heron Country Club, Herongate, Brentwood CM13 3LW",
        latitude=51.584599,
        longitude=0.362301,
        sports=["padel"],
    )
    results = asyncio.run(crawler.ScraperCoroutines([venue], _dates))
    print(f"Got {len(results)} slots")
    print(results[:3])
