import asyncio
import itertools
from datetime import date
from typing import Any, Coroutine, List

import httpx

from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.core.interfaces import BaseCrawler
from sportscanner.crawlers.parsers.core.schemas import (
    AdditionalRequestMetadata,
    RawResponseData,
    RequestDetailsWithMetadata,
    UnifiedParserSchema,
)
from sportscanner.crawlers.parsers.stratfordpadel.core.strategy import (
    BOOKING_URL,
    BROWSER_HEADERS,
    StratfordPadelResponseParserStrategy,
    fetch_cuadro_raw,
    fetch_session_key_and_cookies,
)
from sportscanner.crawlers.parsers.utils import validate_api_response
from sportscanner.logger import logging
from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.variables import settings


class StratfordPadelCrawler(BaseCrawler):
    """Stratford Padel Club runs on TPC-MatchPoint (matchpoint.com.es), an
    ASP.NET WebForms booking platform. Availability is viewable anonymously,
    but it does not fit BaseCrawler's one-request-per-(venue, date) shape: each
    crawl needs a two-phase handshake first (GET Grid.aspx to establish the
    ASP.NET session cookie and harvest a per-page-load obfuscated key, then
    POST that key with every srvc.aspx page-method call). So ScraperCoroutines
    is overridden with its own fetch loop - the same bypass pattern Matchi/
    Playtomic use - capped by asyncio.Semaphore per repo convention.

    Plain httpx works: no TLS-fingerprinting WAF on this host (verified live).
    See docs/clubs/stratford-padel.md."""

    def __init__(self):
        super().__init__(
            request_strategy=None,
            response_parser_strategy=StratfordPadelResponseParserStrategy(),
            organisation_website="https://stratfordpadelclub.matchpoint.com.es",
        )

    async def _fetch_date(
        self,
        client: httpx.AsyncClient,
        session_key: str,
        sports_venue: SportsVenue,
        fetch_date: date,
    ) -> List[UnifiedParserSchema]:
        raw_payload = await fetch_cuadro_raw(client, session_key, fetch_date)
        if not isinstance(raw_payload, dict) or not raw_payload.get("Columnas"):
            logging.warning(
                f"Stratford Padel: empty cuadro for {fetch_date} - possibly outside "
                f"the bookable window or session expired"
            )
            return []
        request_details = RequestDetailsWithMetadata(
            url=BOOKING_URL,
            headers=BROWSER_HEADERS,
            payload={"fecha": fetch_date.strftime("%d/%m/%Y")},
            metadata=AdditionalRequestMetadata(
                category="Padel",
                date=fetch_date,
                price=None,
                booking_url=BOOKING_URL,
                sportsCentre=sports_venue,
            ),
        )
        # fetch_cuadro_raw already raised on non-200 and decoded the JSON
        # envelope; validate_api_response is built for response objects so it
        # does not apply to this pre-decoded payload.
        validated_response: dict = raw_payload
        raw_data_obj = RawResponseData(
            content=validated_response,
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
        semaphore = asyncio.Semaphore(
            settings.CRAWLER_MAX_CONCURRENT_REQUESTS_PER_PROVIDER
        )
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                session_key = await fetch_session_key_and_cookies(client)
            except Exception as e:
                logging.error(
                    f"Stratford Padel: grid handshake failed: {type(e).__name__}: {e!r}"
                )
                return []
            if not session_key:
                return []
            logging.info(
                f"Stratford Padel: handshake OK, crawling {len(sports_venues)} venue(s) "
                f"across {len(dates)} date(s)"
            )

            async def bounded(
                venue: SportsVenue, fetch_date: date
            ) -> List[UnifiedParserSchema]:
                async with semaphore:
                    return await self._fetch_date(
                        client, session_key, venue, fetch_date
                    )

            results = await asyncio.gather(
                *(
                    bounded(venue, fetch_date)
                    for venue, fetch_date in itertools.product(sports_venues, dates)
                ),
                return_exceptions=True,
            )
        all_slots: List[UnifiedParserSchema] = []
        for r in results:
            if isinstance(r, Exception):
                logging.error(f"Stratford Padel task raised: {r!r}")
            elif r:
                all_slots.extend(r)
        return all_slots


def coroutines(search_dates: List[date]):
    """Pipeline entry point. delta=None: the API itself enforces its own
    bookable window (StrFechaMin..StrFechaMax in every cuadro response) and
    answers out-of-window dates with an empty grid rather than an error."""
    return StratfordPadelCrawler().coroutines(search_dates, sport="padel", delta=None)


if __name__ == "__main__":
    from rich import print

    _dates = [date.today(), date.today()]
    crawler = StratfordPadelCrawler()
    venue = SportsVenue(
        composite_key="00000000",
        organisation="Stratford Padel Club",
        organisation_website="https://stratfordpadelclub.matchpoint.com.es",
        venue_name="Stratford Padel Club",
        slug="stratford-padel-club",
        postcode="E15 2AE",
        address="221 High Street, Stratford, London E15 2AE",
        latitude=51.534693,
        longitude=-0.005559,
        sports=["padel"],
    )
    results = asyncio.run(crawler.ScraperCoroutines([venue], _dates[:1]))
    print(results)
    print(f"Got {len(results)} slots")
