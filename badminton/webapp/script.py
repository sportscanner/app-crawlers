from rich import print
from datetime import datetime
from datetime import date, timedelta
from tqdm import tqdm
import itertools
from tabulate import tabulate
import pandas as pd
import json
import requests
import json
import time

ALL_AVAILABLE_SLOTS = []

def extract_slot_time(div):
    slot_time_range = div.find(class_="ClassCardComponent__ClassTime-sc-1v7d176-3").text.strip()
    # parsing in python datetime format
    time_range = slot_time_range
    start_time_str, end_time_str = time_range.split(' - ')

    # Convert start time string to datetime object
    start_time = datetime.strptime(start_time_str, '%H:%M').time()

    # Convert end time string to datetime object
    end_time = datetime.strptime(end_time_str, '%H:%M').time()
    return start_time, end_time, time_range


def apply_slots_preference_filter(start_time_preference, end_time_preference):
    preferred_slots = []
    start_time_range = datetime.strptime(start_time_preference, '%H:%M').time()
    end_time_range = datetime.strptime(end_time_preference, '%H:%M').time()
    for slot in ALL_AVAILABLE_SLOTS:
        if slot["parsed_start_time"] >= start_time_range and slot["parsed_end_time"] <= end_time_range and int(slot["slots_available"]) > 0:
            preferred_slots.append(slot)
        else:
            pass
    return preferred_slots

def api_requests_to_fetch_slots(sports_centre, date):
    global ALL_AVAILABLE_SLOTS
    url = f"https://better-admin.org.uk/api/activities/venue/{sports_centre['encoded_alias']}/activity/badminton-40min/times?date={date}"

    payload = ""
    headers = {
        'Content-Type': 'application/json',
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://bookings.better.org.uk',
        'Referer': 'https://bookings.better.org.uk/location/john-orwell/badminton-40min/2023-06-13/by-time',
        'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'cross'
    }

    response = requests.request("GET", url, headers=headers, data=payload)

    response_dict = json.loads(response.text)
    # print(f'"sports-centre": {sports_centre} - date: {date} - response: {response}')

    api_response = response_dict["data"]
    if isinstance(api_response, dict):
        # Case 1: Single dictionary
        for _key, response_block in api_response.items():
            ALL_AVAILABLE_SLOTS.append(
                {
                    "venue": sports_centre["name"],
                    "date": datetime.strptime(str(date), "%Y-%m-%d").date(),
                    "formatted_time": f"{response_block['starts_at']['format_24_hour']} - {response_block['ends_at']['format_24_hour']}",
                    "parsed_start_time": datetime.strptime(response_block['starts_at']['format_24_hour'], '%H:%M').time(),
                    "parsed_end_time": datetime.strptime(response_block['ends_at']['format_24_hour'], '%H:%M').time(),
                    "category": response_block['name'],
                    "price": "",
                    "slots_available": response_block['spaces']
                }
            )
    else:
        if len(api_response) > 0:
            for response_block in api_response:
                ALL_AVAILABLE_SLOTS.append(
                    {
                        "venue": sports_centre["name"],
                        "date": datetime.strptime(str(date), "%Y-%m-%d").date(),
                        "formatted_time": f"{response_block['starts_at']['format_24_hour']} - {response_block['ends_at']['format_24_hour']}",
                        "parsed_start_time": datetime.strptime(response_block['starts_at']['format_24_hour'], '%H:%M').time(),
                        "parsed_end_time": datetime.strptime(response_block['ends_at']['format_24_hour'], '%H:%M').time(),
                        "category": response_block['name'],
                        "price": "",
                        "slots_available": response_block['spaces']
                    }
                )

def reset_results_cache():
    global ALL_AVAILABLE_SLOTS
    ALL_AVAILABLE_SLOTS = []
def metadata(dates, start_time, end_time):
    print("----------- Preferences ------")
    print("Dates: " + str(dates))
    print("Time Range: " + start_time + " - " + end_time)
    print("----------------------------------")

def filter_and_transform_results(start_time, end_time):
    # Combine the results from all the executions
    global ALL_AVAILABLE_SLOTS
    _to_dataframe = pd.DataFrame(
                        apply_slots_preference_filter(
                            start_time_preference = start_time,
                            end_time_preference = end_time
                        )
                    ).sort_values(by=['date', 'parsed_start_time'], ascending=True)\
                        .drop(columns=["parsed_start_time", "parsed_end_time", "category", "price"], axis=1)
    # Chain the transformations to format the 'date' column
    _to_dataframe['date'] = pd.to_datetime(_to_dataframe['date']).dt.strftime('%Y-%m-%d (%A)')
    return _to_dataframe.reset_index(drop=True)

def main(dates, start_time, end_time):
    metadata(dates, start_time, end_time)
    # GLOBAL: Read the JSON file
    with open('./mappings.json', 'r') as file:
        json_data = json.load(file)

    # Convert the JSON data to a list of dictionaries
    sports_centre_lists = list(json_data.values())
    parameter_sets = [(x, y) for x, y in itertools.product(sports_centre_lists, dates)]

    # Start the timer
    process_start_time = time.time()

    with tqdm(total=len(parameter_sets)) as pbar:
        for (sports_centre, date) in parameter_sets:
            api_requests_to_fetch_slots(sports_centre, date)
            pbar.update(1)

    # Stop the timer
    process_end_time = time.time()

    # Calculate the elapsed time
    elapsed_time = process_end_time - process_start_time
    # Print the elapsed time
    print(f"Elapsed fetch time: {elapsed_time} seconds")

    slots_dataframe = filter_and_transform_results(start_time, end_time)
    # print(
    #     tabulate(
    #         slots_dataframe,
    #         headers='keys', 
    #         tablefmt='psql',
    #         showindex='never'
    #     )
    # )
    return slots_dataframe

if __name__ == "__main__":
    today = date.today()
    raw_dates = [today + timedelta(days=i) for i in range(6)]
    dates = [date.strftime("%Y-%m-%d") for date in raw_dates]
    start_time, end_time = "17:30", "22:00"
    main(dates, start_time, end_time)