import base64
import datetime
from datetime import date, timedelta

import httpx
from bs4 import BeautifulSoup
from rich import print


def group_dates_by_week_startdate(dates):
    """Groups a list of datetime.date objects into weeks.

    Args:
      dates: A list of datetime.date objects.

    Returns:
      A dictionary where keys are weeks as strings (e.g., "2025-W01") and values are lists of dates belonging to that week.
    """
    weeks = {}
    for date_obj in dates:
        # Calculate the start of the week (Monday)
        weekday = date_obj.weekday()  # Monday is 0, Sunday is 6
        start_of_week = date_obj - timedelta(days=weekday)
        weeks.setdefault(start_of_week, []).append(date_obj)

    return weeks


headers = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "no-cache",
    "referer": "https://schoolhire.co.uk/london-southwark/notredame/badminton-court/28057?date=",
    "user-agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
}


def parse_calendar_response(response):
    """Parses the API response to extract calendar information."""

    # Decode the base64 string
    html_string = base64.b64decode(response["base64WeekViewHTML"]).decode("utf-8")

    # Parse the HTML
    soup = BeautifulSoup(html_string, "html.parser")
    # Extract dates
    dates = [
        th.text.strip() for th in soup.find("tr", class_="week-head").find_all("th")
    ]

    # Extract availability slots for each day
    availability_data = []
    for week_element in soup.find_all("tr", class_="week-element"):
        day_cells = week_element.find_all("td", class_="open-day availability")
        for day_index, day_cell in enumerate(day_cells):
            slots = [div.text.strip() for div in day_cell.find_all("div")]
            availability_data.append({"date": dates[day_index], "slots": slots})

    return availability_data


#
# # Example usage
# api_response = {
#     "renderer": "facility",
#     "base64WeekViewHTML": "YOUR_BASE64_STRING"
# }

if __name__ == "__main__":
    # Example usage
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(50)]
    grouped_dates = group_dates_by_week_startdate(dates)
    week_startdates_for_request = list(grouped_dates.keys())

    venue_id = 28057
    for fetch_date in week_startdates_for_request:
        RFC850_date_format = fetch_date.strftime("%a%2C+%d+%b+%Y")
        url = f"https://schoolhire.co.uk/calendar.json?facility_id={venue_id}&date={RFC850_date_format}"

        api_response = httpx.get(url, headers=headers).json()
        calendar_data = parse_calendar_response(api_response)
        print(calendar_data)
