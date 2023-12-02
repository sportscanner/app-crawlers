import json
from loguru import logger as logging
from datetime import date, datetime, timedelta


def align_api_responses(api_response):
    aligned_api_response = []
    if isinstance(api_response, dict):
        aligned_api_response.extend(
            [response_block for _key, response_block in api_response.items()]
        )
    else:
        if len(api_response) > 0:
            aligned_api_response.extend(
                [response_block for response_block in api_response]
            )
    logging.success("Data aligned with overall schema")
    return aligned_api_response


def parse_api_response(response_block):
    return {
        "venue": response_block["venue_slug"],
        "name": response_block["venue_name"],
        "date": datetime.strptime(str(response_block["date"]), "%Y-%m-%d").date(),
        "formatted_time": f"{response_block['starts_at']['format_24_hour']} - {response_block['ends_at']['format_24_hour']}",
        "parsed_start_time": datetime.strptime(
            response_block["starts_at"]["format_24_hour"], "%H:%M"
        ).time(),
        "parsed_end_time": datetime.strptime(
            response_block["ends_at"]["format_24_hour"], "%H:%M"
        ).time(),
        "category": response_block["name"],
        "price": "",
        "slots_available": response_block["spaces"],
    }
