def generate_api_call_params(sports_centre, date):
    url = f"https://better-admin.org.uk/api/activities/venue/{sports_centre['encoded_alias']}/activity/badminton-40min/times?date={date}"
    headers = {"Origin": "https://bookings.better.org.uk"}
    payload = {}
    return url, headers, payload


def get_slots(sports_centre, date):
    url, headers, payload = generate_api_call_params(sports_centre, date)
    logging.info(f"Requests URL: {url}")

    response = requests.request("GET", url, headers=headers, data=payload)
    if response.status_code == 200:
        response_dict = json.loads(response.text)
        logging.debug(f"API Response:\n{response_dict}\n")
        return response_dict.get("data")
    else:
        logging.error(f"Request failed with status code {response.status_code}")
        return None
