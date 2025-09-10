import sportscanner.storage.postgres.tables
from sportscanner.crawlers.parsers.core.schemas import RequestDetailsWithMetadata, AdditionalRequestMetadata
from sportscanner.crawlers.parsers.core.interfaces import AbstractRequestStrategy, BaseCrawler
from datetime import date, timedelta
from typing import List, Optional, Dict
from sportscanner.crawlers.helpers import override
import datetime
from loguru import logger as logging

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.decathlon.core.strategy import DecathlonResponseParserStrategy, DecathlonTaskCreationStrategy
from sportscanner.crawlers.parsers.decathlon.core.utils import get_utc_timestamps
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
# In your main script or pipeline orchestrator
from rich import print

class DecathlonPickleballRequestStrategy(AbstractRequestStrategy):
    """
    If there are multiple variations like Pickleball-40 / Pickleball-60 min, add those here
    These should be all possible requests for a particular venue
    """
    @override
    def generate_request_details(
            self, sports_venue: sportscanner.storage.postgres.tables.SportsVenue, fetch_date: date, token: Optional[str] = None
    ) -> List[RequestDetailsWithMetadata]:
        request_generator_list = []
        activityId = sports_venue.slug
        now_utc = datetime.datetime.now(datetime.UTC)
        formatted_timestamp: str = now_utc.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        url = (
            f"https://api-eu.decathlon.net/activities/v2/activities/{activityId}/timeslots?timeslotStatus=PUBLISHED&excludeFull=false&startDate={formatted_timestamp}&sort%5Bby%5D=startDate&sort%5Border%5D=asc&pagination%5Bfrom%5D=0&pagination%5Blimit%5D=100"
        )
        logging.debug(url)
        headers: Dict = {
            'cache-control': 'no-cache',
            'referer': 'https://activities.decathlon.co.uk/',
            'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'accept': 'application/json, text/plain, */*',
            'x-api-key': '666565be-422c-4b54-8138-682de3b95aee',
        }
        payload: Dict = {}
        request_generator_list.append(
            RequestDetailsWithMetadata(
                url=url,
                headers=headers,
                payload=payload,
                token=None,
                cookies=None,
                metadata=AdditionalRequestMetadata(
                    category="Pickleball",
                    date=None,
                    price=None,
                    booking_url=f"https://activities.decathlon.co.uk/en-GB/sport-activities/details/{activityId}",
                    sportsCentre=sports_venue
                )
            )
        )
        return request_generator_list


class DecathlonCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(
            request_strategy = DecathlonPickleballRequestStrategy(),
            response_parser_strategy = DecathlonResponseParserStrategy(),
            task_creation_strategy = DecathlonTaskCreationStrategy(),
            organisation_website = "https://decathlon.co.uk/"
        )


def run(
    crawler: BaseCrawler,
    search_dates: List[date],
    sport_venues_composite_ids: List[str]
) -> List[UnifiedParserSchema]:
    sport_venues_to_crawl: List[
        sportscanner.storage.postgres.tables.SportsVenue] = crawler.query_sport_venues_details(sport_venues_composite_ids)
    if not sport_venues_to_crawl:
        logging.warning(f"No item contexts found for identifiers: {sport_venues_composite_ids} for this crawler.")
        return []
    return crawler.crawl(sport_venues_to_crawl, search_dates)

def coroutines(search_dates: List[date]):
    crawler = DecathlonCrawler()
    sport_venues_to_crawl: List[
        sportscanner.storage.postgres.tables.SportsVenue] = crawler.get_venues_by_sport_offering(sport="pickleball")
    if not sport_venues_to_crawl:
        logging.warning("No venues found for this organisation / sports offerings")
        return []
    return crawler.ScraperCoroutines(sport_venues_to_crawl, search_dates[0:1]) # Limiting to 1 day for coroutines


if __name__ == "__main__":
    logging.info("Mocking up input data (user inputs) for pipeline")
    _dates = [
        date.today() + timedelta(days=2)
    ]
    print(f"Dates to search for: {_dates}")
    _sport_venues_composite_ids = ["1fb9060d", "6f6b0f6a"]
    logging.info(f"Running DecathlonCrawler crawler for slugs: {_sport_venues_composite_ids}")
    parsedResults = run(
        crawler = DecathlonCrawler(),
        search_dates = _dates,
        sport_venues_composite_ids = _sport_venues_composite_ids
    )
    print(parsedResults)
    logging.success(f"DecathlonCrawler finished. Got {len(parsedResults)} results.")
