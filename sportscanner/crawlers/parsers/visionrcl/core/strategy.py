from datetime import date
from typing import Dict, List, Optional

from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.core.interfaces import AbstractRequestStrategy
from sportscanner.crawlers.parsers.core.schemas import (
    AdditionalRequestMetadata,
    RequestDetailsWithMetadata,
)
from sportscanner.logger import logging
from sportscanner.storage.postgres.tables import SportsVenue

TENANT_BOOKING_HOST = "https://vision.bookings.flow.onl"
API_BASE = "https://flow.onl/api"


class VisionRclRequestStrategy(AbstractRequestStrategy):
    """Shared request builder for Vision RCL's flow.onl tenant.

    Vision RCL is a Gladstone deployment white-labelled at
    vision.bookings.flow.onl, same engine as Better/GLL and Active Lambeth.
    Difference vs both: this tenant is v2-only and its activity slugs are the
    category slugs with a /v2 suffix (e.g. badminton/v2, squash-60/v2), not
    duration-named activities like badminton-40min. Subclasses only supply
    `activity_slugs` and `category`.
    """

    activity_slugs: List[str] = []
    category: str = ""

    @override
    def generate_request_details(
        self, sports_venue: SportsVenue, fetch_date: date, token: Optional[str] = None
    ) -> List[RequestDetailsWithMetadata]:
        request_generator_list = []
        formatted_date: str = fetch_date.strftime("%Y-%m-%d")
        for activity_slug in self.activity_slugs:
            url = (
                f"{API_BASE}/activities/venue/"
                f"{sports_venue.slug}/activity/{activity_slug}/times?date={formatted_date}"
            )
            logging.debug(url)
            headers = {
                "origin": TENANT_BOOKING_HOST,
                "referer": f"{TENANT_BOOKING_HOST}/location/{sports_venue.slug}/{activity_slug}/{formatted_date}/by-time",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            }
            payload: Dict = {}
            request_generator_list.append(
                RequestDetailsWithMetadata(
                    url=url,
                    headers=headers,
                    payload=payload,
                    token=None,
                    cookies=None,
                    metadata=AdditionalRequestMetadata(
                        category=self.category,
                        date=fetch_date,
                        price=None,
                        booking_url=f"{TENANT_BOOKING_HOST}/location/{sports_venue.slug}/{activity_slug}/{formatted_date}/by-time/",
                        sportsCentre=sports_venue,
                    ),
                )
            )
        return request_generator_list
