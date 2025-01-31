import httpx
from fontTools.subset import prune_hints
from pydantic_core.core_schema import model_schema
from rich import print
from typing import Optional, List, Dict
from pydantic import BaseModel
from loguru import logger as logging

from sportscanner.crawlers.parsers.towerhamlets.Authenticate import get_authorization_token
from sportscanner.crawlers.parsers.towerhamlets.schemas import Activity

token = get_authorization_token()

def generate_headers() -> Dict:
    return {
        "authorization": f"Bearer {token}",
        "referer": f"https://towerhamletscouncil.gladstonego.cloud/book/calendar/MACT000010?activityDate=2025-01-26T08:00:00.000Z",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    }

def generate_url() -> str:
    # formatted_search_date = fetch_date.strftime("%Y/%m/%d")
    return (
        "https://towerhamletscouncil.gladstonego.cloud/api/availability/V2/sessions?siteIds=MEPLS&activityIDs=MACT000010&webBookableOnly=true&dateFrom=2025-01-29T00:00:00.000Z&locationId="
    )

response = httpx.get(
    generate_url(), headers=generate_headers()
)
content_type = response.headers.get("content-type", "")
match response.status_code:
    case 200:
        json_response = response.json()
        _modelling: List[Activity] = [Activity(**x) for x in json_response]
        print([x.capacity for x in _modelling])
        logging.debug(
            f"Request success: Raw response for url: {generate_url()} \n{json_response}"
        )
    case _:
        logging.error(
            f"Response status code is not: Response [200 OK]"
            f"\nResponse: {response}"
        )