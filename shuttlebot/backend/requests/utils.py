from datetime import datetime
from typing import Optional

from loguru import logger as logging
from pydantic import BaseModel

from shuttlebot.backend.parsers.better.schemas import BetterBookingResponseModel


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
    logging.debug("Data aligned with overall schema")
    return aligned_api_response


class ResponseBlock(BaseModel):
    venue_slug: str
    venue_name: str
    date: str
    starts_at: dict
    ends_at: dict
    name: str
    spaces: int
    nearest_distance: Optional[float]


def transform_api_response(response_block: dict):
    # Parse the response block into a ResponseBlock model instance
    response_block_model = ResponseBlock(**response_block)
    return {
        "venue": response_block_model.venue_slug,
        "name": response_block_model.venue_name,
        "date": datetime.strptime(response_block_model.date, "%Y-%m-%d").date(),
        "formatted_time": f"{response_block_model.starts_at['format_24_hour']} - "
        f"{response_block_model.ends_at['format_24_hour']}",
        "parsed_start_time": datetime.strptime(
            response_block_model.starts_at["format_24_hour"], "%H:%M"
        ).time(),
        "parsed_end_time": datetime.strptime(
            response_block_model.ends_at["format_24_hour"], "%H:%M"
        ).time(),
        "category": response_block_model.name,
        "price": "",
        "slots_available": response_block_model.spaces,
        "nearest_distance": response_block_model.nearest_distance,
    }
