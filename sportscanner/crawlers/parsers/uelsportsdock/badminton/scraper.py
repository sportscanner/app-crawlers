from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.crawlers.parsers.core.schemas import RequestDetailsWithMetadata, AdditionalRequestMetadata
from sportscanner.crawlers.parsers.core.interfaces import AbstractRequestStrategy, BaseCrawler
from datetime import date
from typing import List, Optional
from sportscanner.crawlers.helpers import override

from sportscanner.logger import logging

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.uelsportsdock.core.strategy import UELSportsDockResponseParserStrategy
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema


class UELSportsDockBadmintonRequestStrategy(AbstractRequestStrategy):
    """
    UEL SportsDock runs on the same 'Leisure Hub' (LhWeb) booking platform as
    CitySport (see sportscanner/crawlers/parsers/citysports/) - identical
    anonymous timetable API, no auth needed to view availability (only to
    complete an actual booking). Unlike CitySport, this instance is not behind
    a TLS-fingerprinting WAF, so it uses BaseCrawler's standard fetch loop
    directly rather than the curl_cffi bypass CitySport needs. See
    docs/clubs/uel-sportsdock.md.
    """
    @override
    def generate_request_details(
            self, sports_venue: SportsVenue, fetch_date: date, token: Optional[str] = None
    ) -> List[RequestDetailsWithMetadata]:
        request_generator_list = []
        formatted_date: str = fetch_date.strftime("%Y/%m/%d")
        url = (
            f"https://horizons.uel.ac.uk/LhWeb/en/api/Sites/1/Timetables/ActivityBookings"
            f"?date={formatted_date}&pid=0"
        )
        logging.debug(url)
        headers = {
            "Referer": "https://horizons.uel.ac.uk/LhWeb/en/Public/Bookings",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        }
        payload: dict = {}
        request_generator_list.append(
            RequestDetailsWithMetadata(
                url=url,
                headers=headers,
                payload=payload,
                token=None,
                cookies=None,
                metadata=AdditionalRequestMetadata(
                    category="Badminton",
                    date=fetch_date,
                    price=None,
                    booking_url="https://horizons.uel.ac.uk/LhWeb/en/Public/Bookings/",
                    sportsCentre=sports_venue
                )
            )
        )
        return request_generator_list


class UELSportsDockCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(
            request_strategy = UELSportsDockBadmintonRequestStrategy(),
            response_parser_strategy = UELSportsDockResponseParserStrategy(),
            organisation_website = "https://www.uel.ac.uk"
        )


def run(
    crawler: BaseCrawler,
    search_dates: List[date],
    sport_venues_composite_ids: List[str]
) -> List[UnifiedParserSchema]:
    sport_venues_to_crawl: List[
        SportsVenue] = crawler.query_sport_venues_details(sport_venues_composite_ids)
    if not sport_venues_to_crawl:
        logging.warning(f"No item contexts found for identifiers: {sport_venues_composite_ids} for this crawler.")
        return []
    return crawler.crawl(sport_venues_to_crawl, search_dates)


def coroutines(search_dates: List[date]):
    # delta=None: no per-venue date-window narrowing needed - confirmed live
    # that this venue's API returns valid data even 3+ weeks out, unlike
    # Better/GLL-style providers that reject far-future dates with a 422.
    return UELSportsDockCrawler().coroutines(search_dates, sport="badminton", delta=None)


if __name__ == "__main__":
    from datetime import timedelta
    from rich import print
    logging.info("Mocking up input data (user inputs) for pipeline")
    _dates = [date.today() + timedelta(days=1)]
    _sport_venues_composite_ids = ["e91e28d4"]  # UEL SportsDock
    logging.info(f"Running UELSportsDockCrawler crawler for slugs: {_sport_venues_composite_ids}")
    parsedResults = run(
        crawler = UELSportsDockCrawler(),
        search_dates = _dates,
        sport_venues_composite_ids = _sport_venues_composite_ids
    )
    print(parsedResults)
    logging.success(f"UELSportsDockCrawler finished. Got {len(parsedResults)} results.")
