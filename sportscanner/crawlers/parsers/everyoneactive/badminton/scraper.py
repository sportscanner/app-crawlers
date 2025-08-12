import sportscanner.storage.postgres.tables
from sportscanner.crawlers.parsers.core.schemas import RequestDetailsWithMetadata, AdditionalRequestMetadata
from sportscanner.crawlers.parsers.core.interfaces import AbstractRequestStrategy, BaseCrawler
from datetime import date, timedelta
from typing import List, Optional, Dict
from sportscanner.crawlers.helpers import override

from loguru import logger as logging

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.everyoneactive.core.strategy import EveryoneActiveTaskCreationStrategy, EveryoneActiveResponseParserStrategy
from sportscanner.crawlers.parsers.everyoneactive.core.utils import get_utc_timestamps
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
# In your main script or pipeline orchestrator

class EveryoneActiveBadmintonRequestStrategy(AbstractRequestStrategy):
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
            "queen-mother-sports-centre": "155BADMINTON1",
            "st-augustines-sports-centre": "156BADMINTON1",
            "reynolds-sports-centre": "119BADM050SH001",
            "moberly-sports-centre": "160BADM055SH001",
            "little-venice-sports-centre": "158BADMINTON1",
            "jubilee-community-leisure-centre": "282BADM060SH001",
            "church-street-community-leisure-centre": "270BADM060SH001",
            "academy-sport": "262BADM060SH001",
            "vale-farm-sports-centre": "101BADMINTON1",
            "greenford-sports-centre": "118BADM050SH001",
            "harrow-leisure-centre": "091BADMINT001"
        }
        activityId = activityIds.get(sports_venue.slug, None)
        from_utc, to_utc = get_utc_timestamps(fetch_date)
        url = (
            f"https://caching.everyoneactive.com/aws/api/activity/availability?toUTC={to_utc}&activityId={activityId}&fromUTC={from_utc}&locale=en_GB"
        )
        logging.debug(url)
        headers: Dict = {
            'Host': 'caching.everyoneactive.com',
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
                    category="Badminton",
                    date=fetch_date,
                    price="£18.0",
                    booking_url=f"https://www.everyoneactive.com/centre/{sports_venue.slug}/",
                    sportsCentre=sports_venue
                )
            )
        )
        return request_generator_list


class EveryoneActiveCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(
            request_strategy = EveryoneActiveBadmintonRequestStrategy(),
            response_parser_strategy = EveryoneActiveResponseParserStrategy(),
            task_creation_strategy = EveryoneActiveTaskCreationStrategy(),
            organisation_website = "https://www.everyoneactive.com/"
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
    crawler = EveryoneActiveCrawler()
    sport_venues_to_crawl: List[
        sportscanner.storage.postgres.tables.SportsVenue] = crawler.get_venues_by_sport_offering(sport="badminton")
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
    _sport_venues_composite_ids = ["b03e14b9"]
    logging.info(f"Running EveryoneActiveCrawler crawler for slugs: {_sport_venues_composite_ids}")
    parsedResults = run(
        crawler = EveryoneActiveCrawler(),
        search_dates = _dates,
        sport_venues_composite_ids = _sport_venues_composite_ids
    )
    logging.success(f"EveryoneActiveCrawler finished. Got {len(parsedResults)} results.")
