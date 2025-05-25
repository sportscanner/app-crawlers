import sportscanner.storage.postgres.tables
from sportscanner.crawlers.parsers.core.schemas import RequestDetailsWithMetadata, AdditionalRequestMetadata
from sportscanner.crawlers.parsers.core.interfaces import AbstractRequestStrategy, BaseCrawler
from datetime import date
from typing import List, Optional, Coroutine, Any
from sportscanner.crawlers.helpers import override

from loguru import logger as logging

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.better.core.strategy import BetterLeisureResponseParserStrategy, \
    BetterLeisureTaskCreationStrategy
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
# In your main script or pipeline orchestrator
from sportscanner.crawlers.parsers.utils import formatted_date_list, \
    filter_for_allowable_search_dates_for_venue  # Keep this


class BetterLeisureBadmintonRequestStrategy(AbstractRequestStrategy):
    """
    If there are multiple variations like badminton-40 / badminton-60 min, add those here
    These should be all possible requests for a particular venue
    """
    @override
    def generate_request_details(
            self, sports_venue: sportscanner.storage.postgres.tables.SportsVenue, fetch_date: date, token: Optional[str] = None
    ) -> List[RequestDetailsWithMetadata]:
        request_generator_list = []
        activityIds = {
            0: "badminton-40min",
            1:"badminton-60min"
        }
        formatted_date: str = fetch_date.strftime('%Y-%m-%d')  # YYYY-MM-DD
        for activityId in activityIds.values():
            url = (
                f"https://better-admin.org.uk/api/activities/venue/"
                f"{sports_venue.slug}/activity/{activityId}/times?date={formatted_date}"
            )
            logging.debug(url)
            headers: dict = {
                "origin": "https://bookings.better.org.uk",
                "referer": f"https://bookings.better.org.uk/location/{sports_venue.slug}/{activityId}/{formatted_date}/by-time",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
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
                        booking_url="https://bookings.better.org.uk/location/{}/{}/{}/by-time/".format(
                            sports_venue.slug,
                            activityId,
                            formatted_date,
                        ),
                        sportsCentre=sports_venue
                    )
                )
            )
        return request_generator_list


class BetterLeisureCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(
            request_strategy = BetterLeisureBadmintonRequestStrategy(),
            response_parser_strategy = BetterLeisureResponseParserStrategy(),
            task_creation_strategy = BetterLeisureTaskCreationStrategy(),
            organisation_website = "https://www.better.org.uk" # add url stuff using urllib
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
    crawler = BetterLeisureCrawler()
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
        date(2025, 5, 26)
    ]
    _sport_venues_composite_ids = ["c3a8df88"]

    if _sport_venues_composite_ids:
        logging.info(f"Running BetterLeisureCrawler crawler for slugs: {_sport_venues_composite_ids}")
        parsedResults = run(
            crawler = BetterLeisureCrawler(),
            search_dates = _dates,
            sport_venues_composite_ids = _sport_venues_composite_ids
        )
        logging.success(f"BetterLeisureCrawler finished. Got {len(parsedResults)} results.")
    else:
        logging.warning("No venue slugs found for BetterLeisureCrawler crawler example.")