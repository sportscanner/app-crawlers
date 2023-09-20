def generate_api_call_params(sports_centre, date):
    url = f"https://better-admin.org.uk/api/activities/venue/{sports_centre['encoded_alias']}/activity/badminton-40min/times?date={date}"
    headers = {"Origin": "https://bookings.better.org.uk"}
    payload = {}
    return url, headers, payload
