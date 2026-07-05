from sportscanner.logger import logging
from datetime import date, timedelta
from typing import Any, List, Optional


def validate_api_response(response, content_type: str, url: str) -> Optional[Any]:
    """Validate an API response by status code and content type.

    Returns the parsed JSON body on a successful (200 + JSON) response, or
    ``None`` on any failure. Callers treat ``None`` the same as an empty body.
    """
    if response.status_code == 200 and "application/json" in content_type:
        json_response = response.json()
        logging.trace(f"Raw response for url: {url} \n{json_response}")
        return json_response
    elif "application/json" not in content_type:
        logging.error(
            f"Response content-type does not contain 'application/json'"
            f"\nURL: {url}"
            f"\nResponse: {response}"
        )
        return None
    else:
        logging.error(
            f"Request failed: status code {response.status_code}"
            f"\nURL: {url}"
            f"\nResponse: {response}"
        )
        return None


def formatted_date_list(search_dates: List[date]):
    return [x.strftime("%Y-%m-%d") for x in search_dates]


def filter_for_allowable_search_dates_for_venue(search_dates: List[date], delta: int = 6) -> List[date]:
    """
    Filters a list of search dates to only include dates that are also present in the allowable dates list.

    Args:
    search_dates: A list of date objects to be filtered.
    allowable_dates: A list of date objects representing the allowed dates.

    Returns:
    A list of date objects that are present in both the search dates and allowable dates lists.
    """
    today = date.today()
    allowable_dates = [today + timedelta(days=i) for i in range(delta)]
    return [
        search_date for search_date in search_dates if search_date in allowable_dates
    ]