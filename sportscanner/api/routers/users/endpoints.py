from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Request,
    status,
)
from loguru import logger as logging
from pydantic import BaseModel
from rich import print
from typing import List
from sportscanner.api.routers.users.schema.user import (
    UserInCreate,
    UserOutput,
)
from sportscanner.api.routers.users.service.userService import UserService
import httpx

from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details

router = APIRouter()


@router.get("/", status_code=status.HTTP_200_OK)
async def get_user_info(
    Authorization: str = Header(
        default=None, title="Bearer JWT token to authenticate user"
    ),
):
    access_token = get_kinde_access_token(
        refresh_token=Authorization
    )
    user_details = get_kinde_user_details(access_token)
    user = UserService().get_user_info(user_details["id"])
    print(user)
    return user


@router.patch("/", status_code=status.HTTP_200_OK)
async def modify_user_info(
    request: Request,
    Authorization: str = Header(
        default=None, title="Bearer JWT token to authenticate user"
    ),
):
    payload = await request.json()
    print(payload)
    access_token = get_kinde_access_token(
        refresh_token=Authorization
    )
    user_details = get_kinde_user_details(access_token)
    UserService().update_user_info(user_details["id"], payload)
    return {"success": True}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def user_onboarding(
    request: Request,
    Authorization: str = Header(
        default=None, description="Bearer token to authenticate user"
    ),
):
    payload = await request.json()
    access_token = get_kinde_access_token(
        refresh_token=Authorization
    )
    user_details = get_kinde_user_details(access_token)
    print(user_details)
    userMetadata = UserInCreate(
        kindeUserId=user_details.get("id"),
        fullName=f"{user_details.get('first_name')} {user_details.get('last_name')}",
        email=user_details.get("preferred_email"),
        postcode=payload.get("postcode"),
        preferredVenues=payload.get("preferredVenues"),
        onboarding=True
    )
    return UserService().create_metadata(
        userMetadata,
        userMetadata.kindeUserId
    )

