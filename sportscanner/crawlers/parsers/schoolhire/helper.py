from datetime import date
from typing import List
from datetime import date, timedelta

def filter_search_dates_for_allowable(search_dates: List[date]) -> List[date]:
    """
    Filters a list of search dates to only include dates that are also present in the allowable dates list.

    Args:
    search_dates: A list of date objects to be filtered.
    allowable_dates: A list of date objects representing the allowed dates.

    Returns:
    A list of date objects that are present in both the search dates and allowable dates lists.
    """
    today = date.today()
    allowable_dates = [today + timedelta(days=i) for i in range(6)]
    return [search_date for search_date in search_dates if search_date in allowable_dates]