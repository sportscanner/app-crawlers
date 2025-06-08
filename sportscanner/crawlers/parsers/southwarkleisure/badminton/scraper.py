import pandas as pd

import sportscanner.storage.postgres.tables
from sportscanner.crawlers.parsers.core.schemas import RequestDetailsWithMetadata, AdditionalRequestMetadata
from sportscanner.crawlers.parsers.core.interfaces import AbstractRequestStrategy, BaseCrawler
from datetime import date, datetime
from typing import List, Optional, Dict
from sportscanner.crawlers.helpers import override, printdf

from loguru import logger as logging

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
# In your main script or pipeline orchestrator

from sportscanner.crawlers.parsers.southwarkleisure.core.mappings import HyperlinkGenerator, Parameters, siteIdsActivityIds
from sportscanner.crawlers.parsers.southwarkleisure.core.strategy import SouthwarkLeisureTaskCreationStrategy
from sportscanner.crawlers.parsers.towerhamlets.core.strategy import TowerHamletsResponseParserStrategy
from sportscanner.crawlers.parsers.utils import formatted_date_list # Keep this


def generate_parameters_set(
    hyperlinks: List[HyperlinkGenerator], venues: List[sportscanner.storage.postgres.tables.SportsVenue]
) -> List[Parameters]:
    # Convert list of SportsVenue to a dictionary for fast lookup
    venue_dict = {venue.slug: venue for venue in venues}
    # Create Parameters objects by matching siteId with slug
    result = [
        Parameters(
            siteId=hyper.siteId,
            activityId=hyper.activityId,
            venue=venue_dict[hyper.siteId],
        )
        for hyper in hyperlinks
        if hyper.siteId in venue_dict
    ]
    return result


def generate_headers(token: str) -> Dict:
    return {
        "Host": f"southwarkcouncil.gladstonego.cloud",
        "Authorization": token,
        # "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    }


def generate_url(hyperlinksAndMetadata: Parameters, search_date: date) -> str:
    def format_search_date(unformatted_date: date) -> str:
        now = datetime.now()
        if search_date == now.date():
            dt = now
        else:
            dt = datetime.combine(search_date, datetime.min.time())
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    formatted_date = format_search_date(search_date)
    generated_url: str = (
        f"https://southwarkcouncil.gladstonego.cloud/api/availability/V2/sessions?siteIds={hyperlinksAndMetadata.siteId}&activityIDs={hyperlinksAndMetadata.activityId}&webBookableOnly=true&dateFrom={formatted_date}&locationId="
    )
    logging.debug(generated_url)
    return generated_url


def generate_payload(hyperlinksAndMetadata: Parameters, search_date: date) -> dict:
    formatted_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    generated_payload: dict = {
        "siteIds": hyperlinksAndMetadata.siteId,
        "activityIDs": hyperlinksAndMetadata.activityId,
        "webBookableOnly": True,
        "dateFrom": formatted_date,
        "locationId": None,
    }
    logging.debug(generated_payload)
    return generated_payload

class SafeFormatDict(dict):
    def __missing__(self, key):
        return f"{{{key}}}"  # Leaves the placeholder in the string

class SouthwarkLeisureBadmintonRequestStrategy(AbstractRequestStrategy):
    """
    If there are multiple variations like badminton-40 / badminton-60 min, add those here
    These should be all possible requests for a particular venue
    """
    @override
    def generate_request_details(
            self, sports_venue: sportscanner.storage.postgres.tables.SportsVenue, fetch_date: date, token: Optional[str] = None
    ) -> List[RequestDetailsWithMetadata]:
        request_generator_list = []
        activityIdsLookupForSiteIds: List[Parameters] = generate_parameters_set(
            siteIdsActivityIds, [sports_venue]
        )
        for params in activityIdsLookupForSiteIds:
            (url, headers, payload) = (
                generate_url(params, fetch_date),
                generate_headers(token),
                generate_payload(params, fetch_date),
            )
            logging.debug(
                f"Fetching data from {url} with headers {headers}"
            )
            booking_url_template = (
                "https://southwarkcouncil.gladstonego.cloud/book/calendar/"
                "{activityId}?activityDate={formatted_date}&previousActivityDate={formatted_previous_day}"
            )
            # Fill only the activityId now
            partial_booking_url = booking_url_template.format_map(SafeFormatDict(activityId=params.activityId))
            request_generator_list.append(
                RequestDetailsWithMetadata(
                    url=url,
                    headers=headers,
                    payload=payload,
                    token=token,
                    cookies=None,
                    metadata=AdditionalRequestMetadata(
                        category="Badminton",
                        date=fetch_date,
                        price="£9.70",
                        booking_url=partial_booking_url,
                        sportsCentre=sports_venue
                    )
                )
            )
        return request_generator_list


class SouthwarkLeisureCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(
            request_strategy = SouthwarkLeisureBadmintonRequestStrategy(),
            response_parser_strategy = TowerHamletsResponseParserStrategy(),
            task_creation_strategy = SouthwarkLeisureTaskCreationStrategy(),
            organisation_website = "https://southwarkleisure.co.uk/"
        )


def run(
    crawler: BaseCrawler,
    search_dates: List[date],
    sport_venues_composite_ids: List[str]
) -> List[UnifiedParserSchema]:
    search_dates: List[date] = search_dates
    logging.warning(
        f"Override search dates as 1 URL response contain Month's data: {formatted_date_list(search_dates)}"
    )
    sport_venues_to_crawl: List[
        sportscanner.storage.postgres.tables.SportsVenue] = crawler.query_sport_venues_details(sport_venues_composite_ids)
    print(sport_venues_to_crawl)
    if not sport_venues_to_crawl:
        logging.warning(f"No item contexts found for identifiers: {sport_venues_composite_ids} for this crawler.")
        return []
    return crawler.crawl(sport_venues_to_crawl, search_dates)


def coroutines(search_dates: List[date]):
    crawler = SouthwarkLeisureCrawler()
    search_dates: List[date] = [
        date.today()
    ]  # Override parameter as 1 URL response contain Month's data
    logging.warning(
        f"Override search dates as 1 URL response contain Month's data: {formatted_date_list(search_dates)}"
    )
    sport_venues_to_crawl: List[
        sportscanner.storage.postgres.tables.SportsVenue] = crawler.get_venues_by_sport_offering(sport="badminton")
    if not sport_venues_to_crawl:
        logging.warning("No venues found for this organisation / sports offerings")
        return []
    return crawler.ScraperCoroutines(sport_venues_to_crawl, search_dates)


if __name__ == "__main__":
    logging.info("Mocking up input data (user inputs) for pipeline")
    _dates = [
        date(2025, 6, 10)
    ]
    _sport_venues_composite_ids = ["f12de0db"]

    parsedResults = run(
        crawler = SouthwarkLeisureCrawler(),
        search_dates = _dates,
        sport_venues_composite_ids = _sport_venues_composite_ids
    )
    df = pd.DataFrame([item.model_dump() for item in parsedResults])
    printdf(df)
    logging.success(f"TowerHamletsCrawler finished. Got {len(parsedResults)} results.")