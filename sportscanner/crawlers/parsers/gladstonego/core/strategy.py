"""Gladstone Go request strategy for the multi-tenant padel venues.

Reuses ``GladstoneGoResponseParserStrategy`` and the anonymous-JWT helper from
the Mytime Active adapter. The only difference is that the portal host, site id
and activity id(s) come from ``GLADSTONE_TENANTS`` instead of being hardcoded
to a single tenant.
"""

from datetime import date
from typing import List, Optional

from sportscanner.crawlers.helpers import override
from sportscanner.crawlers.parsers.core.interfaces import AbstractRequestStrategy
from sportscanner.crawlers.parsers.core.schemas import (
    AdditionalRequestMetadata,
    RequestDetailsWithMetadata,
)
from sportscanner.crawlers.parsers.gladstonego.core.venues import (
    GLADSTONE_TENANTS,
)
from sportscanner.storage.postgres.tables import SportsVenue

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)


class GladstoneGoPadelRequestStrategy(AbstractRequestStrategy):
    category = "Padel"

    @override
    def generate_request_details(
        self, sports_venue: SportsVenue, fetch_date: date, token: Optional[str] = None
    ) -> List[RequestDetailsWithMetadata]:
        tenant = GLADSTONE_TENANTS.get(sports_venue.slug)
        if not tenant:
            return []
        headers = {
            "accept": "application/json",
            "user-agent": USER_AGENT,
            "x-use-sso": "1",
        }
        if token:
            headers["Cookie"] = f"Jwt={token}"
        requests: List[RequestDetailsWithMetadata] = []
        for activity_id in tenant["activity_ids"]:
            url = (
                f"https://{tenant['host']}/api/availability/V2/sessions"
                f"?siteIds={tenant['site_id']}"
                f"&activityIDs={activity_id}"
                f"&webBookableOnly=false"
                f"&dateFrom={fetch_date.isoformat()}"
            )
            requests.append(
                RequestDetailsWithMetadata(
                    url=url,
                    headers=headers,
                    payload={},
                    token=token,
                    cookies=None,
                    metadata=AdditionalRequestMetadata(
                        category=self.category,
                        date=fetch_date,
                        price="",
                        booking_url=(
                            f"https://{tenant['host']}/book/calendar/"
                            f"{activity_id}?activityDate={fetch_date.isoformat()}"
                        ),
                        sportsCentre=sports_venue,
                        provider_site_id=tenant["site_id"],
                    ),
                )
            )
        return requests
