import sportscanner.storage.postgres.tables
from sportscanner.crawlers.parsers.core.schemas import RequestDetailsWithMetadata, AdditionalRequestMetadata
from sportscanner.crawlers.parsers.core.interfaces import AbstractRequestStrategy, BaseCrawler
from datetime import date, timedelta
from typing import List, Optional, Dict
from sportscanner.crawlers.helpers import override

from sportscanner.logger import logging

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.southwarkleisure.core.strategy import SouthwarkLeisureTaskCreationStrategy, SouthwarkLeisureResponseParserStrategy
from sportscanner.crawlers.parsers.southwarkleisure.core.utils import get_utc_timestamps
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
# In your main script or pipeline orchestrator

class SouthwarkLeisurePickleballRequestStrategy(AbstractRequestStrategy):
    """
    If there are multiple variations like Pickleball-40 / Pickleball-60 min, add those here
    These should be all possible requests for a particular venue
    """
    @override
    def generate_request_details(
            self, sports_venue: sportscanner.storage.postgres.tables.SportsVenue, fetch_date: date, token: Optional[str] = None
    ) -> List[RequestDetailsWithMetadata]:
        request_generator_list = []
        activityIds = {
            "CWLC": "CWACT00003", # Pickleball - Canada water leisure centre
        }
        activityId = activityIds.get(sports_venue.slug, None)
        from_utc, to_utc = get_utc_timestamps(fetch_date)
        formatted_date: str = fetch_date.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        url = (
            f"https://southwarkcouncil.gs-signature.cloud/AWS/api/activity/availability?toUTC={to_utc}&activityId={activityId}&fromUTC={from_utc}&locale=en_GB"
        )
        logging.debug(url)
        headers: Dict = {
            'Host': 'southwarkcouncil.gs-signature.cloud',
            'AuthenticationKey': 'M0bi1eProB00king$',
            'Accept': 'application/json,application/json',
            'User-Agent': 'iPhone',
            'Accept-Language': 'en-GB;q=1.0',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json'
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
                    date=fetch_date,
                    price="£11.85",
                    booking_url=f"https://southwarkcouncil.gladstonego.cloud/book/calendar/{activityId}?activityDate={formatted_date}",
                    sportsCentre=sports_venue
                )
            )
        )
        return request_generator_list


class SouthwarkLeisureCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(
            request_strategy = SouthwarkLeisurePickleballRequestStrategy(),
            response_parser_strategy = SouthwarkLeisureResponseParserStrategy(),
            task_creation_strategy = SouthwarkLeisureTaskCreationStrategy(),
            organisation_website = "https://southwarkleisure.co.uk/"
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
    crawler = SouthwarkLeisureCrawler()
    sport_venues_to_crawl: List[
        sportscanner.storage.postgres.tables.SportsVenue] = crawler.get_venues_by_sport_offering(sport="pickleball")
    if not sport_venues_to_crawl:
        logging.warning("No venues found for this organisation / sports offerings")
        return []
    return crawler.ScraperCoroutines(sport_venues_to_crawl, search_dates)


if __name__ == "__main__":
    logging.info("Mocking up input data (user inputs) for pipeline")
    _dates = [
        date.today() + timedelta(days=2)
    ]
    print(f"Dates to search for: {_dates}")
    _sport_venues_composite_ids = ["9dd758e8"]
    logging.info(f"Running SouthwarkLeisureCrawler crawler for slugs: {_sport_venues_composite_ids}")
    parsedResults = run(
        crawler = SouthwarkLeisureCrawler(),
        search_dates = _dates,
        sport_venues_composite_ids = _sport_venues_composite_ids
    )
    print(parsedResults)
    logging.success(f"SouthwarkLeisureCrawler finished. Got {len(parsedResults)} results.")
