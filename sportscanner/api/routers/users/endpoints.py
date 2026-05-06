from fastapi import APIRouter, Header, Query, Request, status
from pydantic import BaseModel
from rich import print
from sqlmodel import Session, or_, select

from sportscanner.api.routers.users.service.userService import UserService
from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details
from sportscanner.storage.postgres.database import engine
from sportscanner.storage.postgres.tables import User

router = APIRouter()


def _kinde_identity(refresh_token: str) -> tuple[str, str, str]:
    """Returns (kinde_user_id, full_name, email) from a refresh token."""
    access_token = get_kinde_access_token(refresh_token=refresh_token)
    d = get_kinde_user_details(access_token)
    full_name = f"{d.get('first_name', '')} {d.get('last_name', '')}".strip()
    return d["id"], full_name, d.get("preferred_email", "")


class UserSearchResult(BaseModel):
    kinde_user_id: str
    full_name: str
    # email intentionally omitted — resolved server-side only at match creation


@router.get("/search", response_model=list[UserSearchResult])
async def search_users(
    q: str = Query(..., min_length=2, description="Search by name"),
    Authorization: str = Header(default=None),
):
    """Search Sportscanner users by name for player lookup. Email is never returned."""
    current_user_id, _, _ = _kinde_identity(Authorization)
    q_lower = f"%{q.lower()}%"
    with Session(engine) as session:
        users = session.exec(
            select(User).where(
                User.kinde_user_id != current_user_id,
                User.full_name.ilike(q_lower),
            ).limit(8)
        ).all()
    return [
        UserSearchResult(
            kinde_user_id=u.kinde_user_id,
            full_name=u.full_name or "Sportscanner User",
        )
        for u in users
    ]


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
        onboarding=body.get("onboarding", None),
    )
    return {"success": True}
