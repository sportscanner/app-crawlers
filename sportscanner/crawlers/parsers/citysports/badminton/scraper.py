import sportscanner.storage.postgres.tables
from sportscanner.crawlers.parsers.core.schemas import RequestDetailsWithMetadata, AdditionalRequestMetadata
from sportscanner.crawlers.parsers.core.interfaces import AbstractRequestStrategy, BaseCrawler
from datetime import date
from typing import List, Optional
from sportscanner.crawlers.helpers import override

from sportscanner.logger import logging

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.citysports.core.strategy import CitySportsResponseParserStrategy, \
    CitySportsTaskCreationStrategy
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
# In your main script or pipeline orchestrator
from sportscanner.crawlers.parsers.utils import formatted_date_list, \
    filter_for_allowable_search_dates_for_venue  # Keep this
from rich import print

class CitySportsBadmintonRequestStrategy(AbstractRequestStrategy):
    """
    If there are multiple variations like badminton-40 / badminton-60 min, add those here
    These should be all possible requests for a particular venue
    """
    @override
    def generate_request_details(
            self, sports_venue: sportscanner.storage.postgres.tables.SportsVenue, fetch_date: date, token: Optional[str] = None
    ) -> List[RequestDetailsWithMetadata]:
        request_generator_list = []
        formatted_date: str = fetch_date.strftime("%Y/%m/%d")
        url = (
            f"https://bookings.citysport.org.uk/LhWeb/en/api/Sites/1/Timetables/ActivityBookings"
            f"?date={formatted_date}&pid=0"
        )
        logging.debug(url)
        headers = {
            "Referer": "https://bookings.citysport.org.uk/LhWeb/en/Public/Bookings",
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
                    booking_url="https://bookings.citysport.org.uk/LhWeb/en/Public/Bookings/",
                    sportsCentre=sports_venue
                )
            )
        )
        return request_generator_list


class CitySportsCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(
            request_strategy = CitySportsBadmintonRequestStrategy(),
            response_parser_strategy = CitySportsResponseParserStrategy(),
            task_creation_strategy = CitySportsTaskCreationStrategy(),
            organisation_website = "https://citysport.org.uk"
        )


def run(
    crawler: BaseCrawler,
    search_dates: List[date],
    sport_venues_composite_ids: List[str]
) -> List[UnifiedParserSchema]:

    allowable_search_dates = filter_for_allowable_search_dates_for_venue(search_dates, delta=6)
    logging.warning(
        f"Search dates for crawler narrowed down to: {formatted_date_list(allowable_search_dates)}"
    )
    sport_venues_to_crawl: List[
        sportscanner.storage.postgres.tables.SportsVenue] = crawler.query_sport_venues_details(sport_venues_composite_ids)
    if not sport_venues_to_crawl:
        logging.warning(f"No item contexts found for identifiers: {sport_venues_composite_ids} for this crawler.")
        return []
    return crawler.crawl(sport_venues_to_crawl, allowable_search_dates)


def coroutines(search_dates: List[date]):
    crawler = CitySportsCrawler()
    allowable_search_dates = filter_for_allowable_search_dates_for_venue(search_dates, delta=6)
    logging.warning(
        f"Search dates for crawler narrowed down to: {formatted_date_list(allowable_search_dates)}"
    )
    sport_venues_to_crawl: List[
        sportscanner.storage.postgres.tables.SportsVenue] = crawler.get_venues_by_sport_offering(sport="badminton")
    if not sport_venues_to_crawl:
        logging.warning("No venues found for this organisation / sports offerings")
        return []
    return crawler.ScraperCoroutines(sport_venues_to_crawl, allowable_search_dates)


if __name__ == "__main__":
    logging.info("Mocking up input data (user inputs) for pipeline")
    _dates = [
        date(2025, 5, 27)
    ]
    _sport_venues_composite_ids = ["99434b56"]
    logging.info(f"Running CitySportsCrawler crawler for slugs: {_sport_venues_composite_ids}")
    parsedResults = run(
        crawler = CitySportsCrawler(),
        search_dates = _dates,
        sport_venues_composite_ids = _sport_venues_composite_ids
    )
    print(parsedResults)
    logging.success(f"CitySportsCrawler finished. Got {len(parsedResults)} results.")
