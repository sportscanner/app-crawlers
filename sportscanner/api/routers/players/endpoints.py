from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel

from sportscanner.api.routers.geolocation.external import get_postcode_metadata
from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details
from sportscanner.storage.postgres.database import engine
from sportscanner.storage.postgres.player_repository import PlayerProfileRepository

router = APIRouter()


def _kinde_identity(refresh_token: str) -> tuple[str, str, str]:
    """Returns (kinde_user_id, full_name, email) from a refresh token."""
    access_token = get_kinde_access_token(refresh_token=refresh_token)
    d = get_kinde_user_details(access_token)
    full_name = f"{d.get('first_name', '')} {d.get('last_name', '')}".strip()
    return d["id"], full_name, d.get("preferred_email", "")


class UpsertPlayerProfileRequest(BaseModel):
    display_name: str
    postcode: str          # full postcode — geocoded server-side
    sports: list
    skill_level: dict
    availability: dict
    is_discoverable: bool = True


@router.get("/near", status_code=status.HTTP_200_OK)
async def get_players_near(
    postcode: str = Query(...),
    radius: float = Query(default=5.0),
    sport: Optional[str] = Query(default=None),
    Authorization: str = Header(default=None),
):
    """Find nearby discoverable players within radius miles of postcode."""
    if not Authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header required")

    user_id, _, _ = _kinde_identity(Authorization)

    geo = get_postcode_metadata(postcode)
    if geo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not geocode postcode: {postcode}",
        )

    repo = PlayerProfileRepository(engine)
    players = repo.find_near(
        lat=geo.result.latitude,
        lon=geo.result.longitude,
        radius_miles=radius,
        exclude_user_id=user_id,
        sport=sport,
    )
    return players


@router.post("/profile", status_code=status.HTTP_200_OK)
async def upsert_player_profile(
    body: UpsertPlayerProfileRequest,
    Authorization: str = Header(default=None),
):
    """Create or update the authenticated user's discoverable player profile."""
    if not Authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header required")

    user_id, _, _ = _kinde_identity(Authorization)

    geo = get_postcode_metadata(body.postcode)
    if geo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not geocode postcode: {body.postcode}",
        )

    postcode_district = body.postcode.strip().split()[0].upper()

    repo = PlayerProfileRepository(engine)
    profile = repo.upsert(
        kinde_user_id=user_id,
        display_name=body.display_name,
        postcode_district=postcode_district,
        latitude=geo.result.latitude,
        longitude=geo.result.longitude,
        sports=body.sports,
        skill_level=body.skill_level,
        availability=body.availability,
        is_discoverable=body.is_discoverable,
    )
    return {
        "kinde_user_id": profile.kinde_user_id,
        "display_name": profile.display_name,
        "postcode_district": profile.postcode_district,
        "sports": profile.sports,
        "skill_level": profile.skill_level,
        "availability": profile.availability,
        "is_discoverable": profile.is_discoverable,
    }


@router.get("/profile", status_code=status.HTTP_200_OK)
async def get_player_profile(
    Authorization: str = Header(default=None),
):
    """Get the authenticated user's own player profile."""
    if not Authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header required")

    user_id, _, _ = _kinde_identity(Authorization)

    repo = PlayerProfileRepository(engine)
    profile = repo.get(user_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player profile not found")

    return {
        "kinde_user_id": profile.kinde_user_id,
        "display_name": profile.display_name,
        "postcode_district": profile.postcode_district,
        "sports": profile.sports,
        "skill_level": profile.skill_level,
        "availability": profile.availability,
        "is_discoverable": profile.is_discoverable,
    }


@router.delete("/profile", status_code=status.HTTP_200_OK)
async def delete_player_profile(
    Authorization: str = Header(default=None),
):
    """Remove the authenticated user's player profile (opt-out of discovery)."""
    if not Authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header required")

    user_id, _, _ = _kinde_identity(Authorization)

    repo = PlayerProfileRepository(engine)
    deleted = repo.delete(user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player profile not found")

    return {"detail": "Player profile deleted"}
