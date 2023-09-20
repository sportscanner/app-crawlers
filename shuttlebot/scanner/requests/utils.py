from datetime import date, datetime, timedelta


def parse_api_response(api_response):
    parsed_api_response = []
    if isinstance(api_response, dict):
        # Case 1: Single dictionary
        for _key, response_block in api_response.items():
            parsed_api_response.append(
                {
                    "venue": response_block["venue_slug"],
                    "date": datetime.strptime(
                        str(response_block["date"]), "%Y-%m-%d"
                    ).date(),
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
            )
    else:
        if len(api_response) > 0:
            for response_block in api_response:
                parsed_api_response.append(
                    {
                        "venue": response_block["venue_slug"],
                        "date": datetime.strptime(
                            str(response_block["date"]), "%Y-%m-%d"
                        ).date(),
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
                )

    return parsed_api_response
