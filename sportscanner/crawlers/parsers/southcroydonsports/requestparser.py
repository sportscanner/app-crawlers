from bs4 import BeautifulSoup

import sportscanner.storage.postgres.tables
from sportscanner.crawlers.parsers.core import RawResponseData, RequestDetailsWithMetadata, AdditionalRequestMetadata
from sportscanner.crawlers.parsers.core.interfaces import AbstractResponseParserStrategy, AbstractAsyncTaskCreationStrategy, AbstractRequestStrategy, BaseCrawler
import pandas as pd
from datetime import date, datetime, time, timedelta
from typing import Any, Coroutine, List, Optional, Tuple
from sportscanner.crawlers.helpers import override

import httpx
from sportscanner.logger import logging
from rich import print

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.schema import UnifiedParserSchema
# In your main script or pipeline orchestrator
from sportscanner.crawlers.parsers.better.helper import filter_search_dates_for_allowable # Keep this if general
from sportscanner.crawlers.parsers.utils import formatted_date_list # Keep this


class SouthCroydonBadmintonRequestStrategy(AbstractRequestStrategy):
    """
    If there are multiple variations like badminton-40 / badminton-60 min, add those here
    These should be all possible requests for a particular venue
    """
    def generate_request_details(self, sports_centre: sportscanner.storage.postgres.tables.SportsVenue, fetch_date: date, activity: Optional[str] = None, token: Optional[str] = None) -> List[RequestDetailsWithMetadata]:
        request_generator_list = []
        url = f"https://www.southcroydonsportsclub.com/booking/badminton-court/?date={fetch_date.strftime('%Y-%m-%d')}"
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'en-US,en;q=0.9',
            'referer': url,
        }
        request_generator_list.append(
            RequestDetailsWithMetadata(
                url=url,
                headers=headers,
                payload={},
                metadata=AdditionalRequestMetadata(
                    category="Badminton",
                    date="2025-05-20",
                    price="£8.0",
                    sportsCentre=sports_centre
                )
            )
        )
        return request_generator_list

class SouthCroydonResponseParserStrategy(AbstractResponseParserStrategy):

    def _extract_date(self, soup: BeautifulSoup) -> str:
        """Extracts the date string from the soup object."""
        date_divs = soup.find_all('div', class_='current')
        for div in date_divs:
            form_text = div.find('form')
            if form_text:
                date_str = form_text.get_text(strip=True)
                if date_str:
                    return date_str
        # Fallback if no date found in a form within 'current' div
        if len(date_divs) > 1:
            date_str = date_divs[1].get_text(strip=True)
            if date_str:
                return date_str
        return "" # Or raise an error if date is mandatory

    def _extract_time_slots(self, soup: BeautifulSoup) -> List[str]:
        """Extracts time slots from the first time-column."""
        time_column = soup.find('div', class_='time-column')
        if time_column:
            return [row.get_text(strip=True) for row in time_column.find_all('div', class_='row')]
        return []

    def _parse_slot_availability(self, slot_div: Any) -> Tuple[str, str]:
        """Parses the availability and booking details for a single slot."""
        bookable_checkbox = slot_div.find('input', class_='bookable-checkbox')
        if bookable_checkbox:
            return "Available", ""
        else:
            booked_div = slot_div.find('div', class_=['block booked', 'booked'])
            if booked_div:
                availability = "Booked"
                title_div = booked_div.find('div', title=True)
                if title_div and title_div.get('title'):
                    booking_details = title_div['title']
                else:
                    booking_details = booked_div.get_text(strip=True) if booked_div.get_text(strip=True) else "Booked"
                return availability, booking_details
        return "Unknown", "" # Default if neither available nor booked found

    def _transform_raw_response_to_structured(self, raw_response: RawResponseData) -> pd.DataFrame:
        soup = BeautifulSoup(raw_response.content, 'html.parser')

        date_str = self._extract_date(soup)
        time_slots = self._extract_time_slots(soup)

        court_data = []
        booking_columns = soup.find_all('div', class_='booking-column')

        for column in booking_columns:
            court_name_tag = column.find('div', class_='header')
            if not court_name_tag:
                continue

            court_name = court_name_tag.get_text(strip=True)
            slots = column.find_all('div', class_='row')

            for j, slot_div in enumerate(slots):
                if j < len(time_slots):
                    _time = time_slots[j]
                    availability, booking_details = self._parse_slot_availability(slot_div)

                    court_data.append({
                        "Date": date_str,
                        "Court": court_name,
                        "Time": _time,
                        "Availability": availability,
                        "BookingDetails": booking_details # Added for completeness, though not used in final schema
                    })
        return pd.DataFrame(court_data)

    def time_extractor(self, time_string: str) -> Tuple[time, time]:
        """Extracts start and end time objects from a time string."""
        parts = time_string.split(' - ')
        if len(parts) != 2:
            raise ValueError(f"Time string format invalid: {time_string}")
        start_time_str, end_time_str = parts[0], parts[1]
        start_time_obj = datetime.strptime(start_time_str, '%H:%M').time()
        end_time_obj = datetime.strptime(end_time_str, '%H:%M').time()
        return start_time_obj, end_time_obj

    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        raw_parsed_df: pd.DataFrame = self._transform_raw_response_to_structured(raw_response)
        available_courts_df = raw_parsed_df[raw_parsed_df['Availability'] == 'Available']

        # Group by 'Date' and 'Time' and count the number of available courts
        aggregated_availability = available_courts_df.groupby(['Date', 'Time']).size().reset_index(name='AvailableCourts')
        aggregated_slots = aggregated_availability.to_dict(orient='records')

        unified_schema_output = []
        for slot in aggregated_slots:
            try:
                start_time, end_time = self.time_extractor(slot["Time"])
                unified_schema_output.append(
                    UnifiedParserSchema(
                        category=raw_response.requestMetadata.metadata.category,
                        starting_time=start_time,
                        ending_time=end_time,
                        date=raw_response.requestMetadata.metadata.date,
                        price=raw_response.requestMetadata.metadata.price,
                        spaces=slot["AvailableCourts"],
                        composite_key=raw_response.requestMetadata.metadata.sportsCentre.composite_key,
                        last_refreshed=raw_response.requestMetadata.metadata.last_refreshed,
                        booking_url=raw_response.requestMetadata.url
                    )
                )
            except ValueError as e:
                print(f"Error parsing time for slot {slot['Time']}: {e}")
                # Potentially log this error or handle it based on your needs

        if unified_schema_output:
            print(unified_schema_output[0])
        return unified_schema_output


class SouthCroydonTaskCreationStrategy(AbstractAsyncTaskCreationStrategy):
    async def _fetch_and_parse_data(self, client: httpx.AsyncClient, request_details: RequestDetailsWithMetadata, parser: AbstractResponseParserStrategy) -> List[UnifiedParserSchema]:
        """Fetches/Parses/Transforms data to a unified schema for a single request"""
        try:
            response = await client.get(request_details.url, headers=request_details.headers) # Add payload if request_details.payload
            response.raise_for_status() # Basic HTTP error checking
            raw_data = RawResponseData(
                content=response.text, # Or .text, depending on content type
                status_code=response.status_code,
                headers=dict(response.headers),
                requestMetadata=request_details
            )
            return parser.parse(raw_data)
        except httpx.HTTPStatusError as e:
            logging.error(f"HTTP error for {request_details.url}: {e}")
        except Exception as e:
            logging.error(f"Error fetching/parsing {request_details.url}: {e}")
        return []

    @override
    def create_tasks_for_item(self, client: httpx.AsyncClient, sports_venue: sportscanner.storage.postgres.tables.SportsVenue, fetch_date: date, request_strategy: AbstractRequestStrategy, response_parser_strategy: AbstractResponseParserStrategy) -> List[Coroutine[Any, Any, List[UnifiedParserSchema]]]:
        tasks: List[Coroutine[Any, Any, List[UnifiedParserSchema]]] = []
        # The request strategy might return one or more requests for a single item context
        request_details_list: List[RequestDetailsWithMetadata] = request_strategy.generate_request_details(sports_venue, fetch_date)
        for req_details in request_details_list:
            tasks.append(self._fetch_and_parse_data(client, req_details, response_parser_strategy))
        return tasks


class SouthCroydonSportsClubCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(
            request_strategy = SouthCroydonBadmintonRequestStrategy(),
            response_parser_strategy = SouthCroydonResponseParserStrategy(),
            task_creation_strategy = SouthCroydonTaskCreationStrategy(),
            organisation_website = "https://www.southcroydonsportsclub.com/"
        )


def run_pipeline_for_crawler(
    crawler: BaseCrawler,
    search_dates: List[date],
    sport_venues_composite_ids: List[str]
) -> List[UnifiedParserSchema]:

    allowable_search_dates = filter_search_dates_for_allowable(search_dates)
    logging.warning(
        f"Search dates for crawler narrowed down to: {formatted_date_list(allowable_search_dates)}"
    )
    sport_venues_to_crawl: List[
        sportscanner.storage.postgres.tables.SportsVenue] = crawler.query_sport_venues_details(sport_venues_composite_ids)
    if not sport_venues_to_crawl:
        logging.warning(f"No item contexts found for identifiers: {sport_venues_composite_ids} for this crawler.")
        return []
    return crawler.crawl(sport_venues_to_crawl, allowable_search_dates)


if __name__ == "__main__":
    logging.info("Mocking up input data (user inputs) for pipeline")
    today = date.today()
    _dates = [today + timedelta(days=i) for i in range(1)]
    _sport_venues_composite_ids = ["dcadfda2"]

    if _sport_venues_composite_ids:
        logging.info(f"Running SouthCroydonSportsClubCrawler crawler for slugs: {_sport_venues_composite_ids}")
        parsedResults = run_pipeline_for_crawler(
            crawler = SouthCroydonSportsClubCrawler(),
            search_dates = _dates,
            sport_venues_composite_ids = _sport_venues_composite_ids
        )
        logging.success(f"SouthCroydonSportsClubCrawler finished. Got {len(parsedResults)} results.")
    else:
        logging.warning("No venue slugs found for SouthCroydonSportsClub crawler example.")