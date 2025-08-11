import logging
from datetime import date, datetime, timedelta
from typing import List, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Query, Request, Path
from rich import print
from sqlalchemy import case, func, text
from sqlmodel import col
from starlette import status
from starlette.responses import JSONResponse

import sportscanner.storage.postgres.database as db
from sportscanner.storage.postgres.tables import BadmintonMasterTable
from sportscanner.api.routers.search.badminton.schemas import SearchCriteria
from sportscanner.api.routers.users.service.userService import UserService
from sportscanner.crawlers.pipeline import *
from sportscanner.storage.postgres.dataset_transform import (
    group_slots_by_attributes,
    sort_and_format_grouped_slots_for_ui,
)
from sportscanner.variables import settings, urljoin

router = APIRouter()

@router.post("/")
async def search(
    filters: SearchCriteria,
    Authorization: Optional[str] = Header(
        default=None, description="Authorization Bearer JWT token"
    ),
):
    """Returns all court availability relevant to specified filters passed via payload"""
    print(filters.model_dump())
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                urljoin(
                    settings.API_BASE_URL,
                    f"/venues/near?postcode={filters.postcode}&distance={filters.radius}",
                )
            )
            json_response = response.json()
        except:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unable to fetch metadata - {filters.postcode} is not a valid UK postcode. Try changing the postcode to another one.",
            )
    data = json_response.get("data")  # Should have this `data` key as per contract
    if filters.analytics.specifiedVenues:
        composite_keys: List[str] = filters.analytics.specifiedVenues
    elif filters.analytics.searchUserPreferredLocations:
        pass
        # jwt_token = AuthHandler.extract_token_from_bearer(Authorization)
        # payload = AuthHandler.decode_jwt(token=jwt_token)
        # if payload and payload["user_id"]:
        #     user = UserService().get_user_info(payload["user_id"])
        #     composite_keys = user.get("preferredVenues", [])
        # else:
        #     raise HTTPException(
        #         status_code=status.HTTP_401_UNAUTHORIZED,
        #         detail="Expired/Invalid Authentication Credentials. Sign out and sign back in so your authentication can be refreshed",
        #     )
    else:
        composite_keys = [x["venue"]["composite_key"] for x in data]

    current_timestamp = datetime.now()

    datetime_expr = func.to_timestamp(
        func.concat(BadmintonMasterTable.date, text("' '"),
                    BadmintonMasterTable.starting_time),
        text("'YYYY-MM-DD HH24:MI:SS'"),
    )

    slots = db.get_all_rows(
        db.engine,
        BadmintonMasterTable,
        db.select(BadmintonMasterTable)
        .where(BadmintonMasterTable.composite_key.in_(composite_keys))
        .where(BadmintonMasterTable.spaces > 0)  # Ignore empty courts
        .where(BadmintonMasterTable.starting_time >= filters.timeRange.starting)
        .where(BadmintonMasterTable.ending_time <= filters.timeRange.ending)
        .where(BadmintonMasterTable.date.in_(filters.dates))
        .where(
            datetime_expr > current_timestamp
        ),  # Ensures only future slots are returned
    )
    grouped_slots = group_slots_by_attributes(
        slots, attributes=("composite_key", "date")
    )
    distance_from_venues_reference = {
        x["venue"]["composite_key"]: x["distance"] for x in data
    }
    _response = sort_and_format_grouped_slots_for_ui(
        grouped_slots, distance_from_venues_reference
    )
    # Function to sort the list
    sorted_response = sorted(
        _response,
        key=lambda x: (
            datetime.strptime(x["date"], "%a, %b %d"),  # Closest date
            x[
                filters.sortBy
            ],
        ),
    )
    logging.warning(f"Time taken for retrieval, transformations, sorting: {datetime.now() - current_timestamp}")
    return {
        "success": True,
        "resultId": f"e34f27a2-d591-486c-9a38-11111",
        "slots": sorted_response,
    }


@router.post("/{composite}")
async def search_by_venue(
    filters: SearchCriteria,
    composite: str = Path(
        description="Composite key identifier to fetch venue information"
    )
):
    """Returns all court availability relevant to specified filters passed via payload"""
    print(filters.model_dump())
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                urljoin(
                    settings.API_BASE_URL,
                    f"/venues/{composite}",
                )
            )
            json_response = response.json()
        except:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unable to fetch metadata - {filters.postcode} is not a valid UK postcode. Try changing the postcode to another one.",
            )
    data = json_response.get("data")  # Should have this `data` key as per contract
    print(data)
    return data
    # if filters.analytics.specifiedVenues:
    #     composite_keys: List[str] = filters.analytics.specifiedVenues
    # elif filters.analytics.searchUserPreferredLocations:
    #     pass
    #     # jwt_token = AuthHandler.extract_token_from_bearer(Authorization)
    #     # payload = AuthHandler.decode_jwt(token=jwt_token)
    #     # if payload and payload["user_id"]:
    #     #     user = UserService().get_user_info(payload["user_id"])
    #     #     composite_keys = user.get("preferredVenues", [])
    #     # else:
    #     #     raise HTTPException(
    #     #         status_code=status.HTTP_401_UNAUTHORIZED,
    #     #         detail="Expired/Invalid Authentication Credentials. Sign out and sign back in so your authentication can be refreshed",
    #     #     )
    # else:
    #     composite_keys = [x["venue"]["composite_key"] for x in data]
    #
    # current_timestamp = datetime.now()
    #
    # datetime_expr = func.to_timestamp(
    #     func.concat(BadmintonMasterTable.date, text("' '"),
    #                 BadmintonMasterTable.starting_time),
    #     text("'YYYY-MM-DD HH24:MI:SS'"),
    # )
    #
    # slots = db.get_all_rows(
    #     db.engine,
    #     BadmintonMasterTable,
    #     db.select(BadmintonMasterTable)
    #     .where(BadmintonMasterTable.composite_key.in_(composite_keys))
    #     .where(BadmintonMasterTable.spaces > 0)  # Ignore empty courts
    #     .where(BadmintonMasterTable.starting_time >= filters.timeRange.starting)
    #     .where(BadmintonMasterTable.ending_time <= filters.timeRange.ending)
    #     .where(BadmintonMasterTable.date.in_(filters.dates))
    #     .where(
    #         datetime_expr > current_timestamp
    #     ),  # Ensures only future slots are returned
    # )
    # grouped_slots = group_slots_by_attributes(
    #     slots, attributes=("composite_key", "date")
    # )
    # distance_from_venues_reference = {
    #     x["venue"]["composite_key"]: x["distance"] for x in data
    # }
    # _response = sort_and_format_grouped_slots_for_ui(
    #     grouped_slots, distance_from_venues_reference
    # )
    # # Function to sort the list
    # sorted_response = sorted(
    #     _response,
    #     key=lambda x: (
    #         datetime.strptime(x["date"], "%a, %b %d"),  # Closest date
    #         x[
    #             filters.sortBy
    #         ],
    #     ),
    # )
    # logging.warning(f"Time taken for retrieval, transformations, sorting: {datetime.now() - current_timestamp}")
    # return {
    #     "success": True,
    #     "resultId": f"e34f27a2-d591-486c-9a38-11111",
    #     "slots": sorted_response,
    # }
    #
