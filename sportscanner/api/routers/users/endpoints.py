from fastapi import APIRouter, Header, Request, status
from rich import print

from sportscanner.api.routers.users.service.userService import UserService
from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details

router = APIRouter()


def _kinde_identity(refresh_token: str) -> tuple[str, str, str]:
    """Returns (kinde_user_id, full_name, email) from a refresh token."""
    access_token = get_kinde_access_token(refresh_token=refresh_token)
    d = get_kinde_user_details(access_token)
    full_name = f"{d.get('first_name', '')} {d.get('last_name', '')}".strip()
    return d["id"], full_name, d.get("preferred_email", "")


@router.get("/", status_code=status.HTTP_200_OK)
async def get_user_profile(
    Authorization: str = Header(default=None),
):
    user_id, _, _ = _kinde_identity(Authorization)
    profile = UserService().get_full_profile(user_id)
    print(profile)
    return profile


@router.post("/", status_code=status.HTTP_201_CREATED)
async def register_user(
    Authorization: str = Header(default=None),
):
    """Called automatically from the callback page on first login."""
    user_id, full_name, email = _kinde_identity(Authorization)
    UserService().register(user_id, full_name, email)
    return {"success": True}


@router.patch("/", status_code=status.HTTP_200_OK)
async def update_user(
    request: Request,
    Authorization: str = Header(default=None),
):
    """
    Expects body:
      { "onboarding": bool, "preferences": { ...any keys... } }
    """
    body = await request.json()
    user_id, full_name, email = _kinde_identity(Authorization)
    print(body)
    UserService().update(
        kinde_user_id=user_id,
        full_name=full_name,
        email=email,
        preferences=body.get("preferences", {}),
        onboarding=body.get("onboarding", False),
    )
    return {"success": True}
