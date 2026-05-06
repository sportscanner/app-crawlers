import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, status

from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details

from .schemas import MatchCreate, MatchOut, MatchSplit, LeaderboardEntry
from .service.matchService import MatchService

router = APIRouter()


def _kinde_identity(refresh_token: str) -> tuple[str, str, str]:
    """Returns (kinde_user_id, full_name, email) from a refresh token."""
    access_token = get_kinde_access_token(refresh_token=refresh_token)
    d = get_kinde_user_details(access_token)
    full_name = f"{d.get('first_name', '')} {d.get('last_name', '')}".strip()
    return d["id"], full_name, d.get("preferred_email", "")


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
async def get_leaderboard(
    sport: Optional[str] = Query(None, description="Filter by sport (badminton, squash, pickleball)"),
    Authorization: str = Header(default=None),
):
    """Global match leaderboard ranked by wins."""
    _kinde_identity(Authorization)
    return MatchService().get_leaderboard(sport=sport)


@router.post("/", response_model=MatchOut, status_code=status.HTTP_201_CREATED)
async def log_match(
    body: MatchCreate,
    Authorization: str = Header(default=None),
):
    """Log a new match with players and scores."""
    kinde_user_id, _, creator_email = _kinde_identity(Authorization)
    return MatchService().create_match(created_by=kinde_user_id, creator_email=creator_email, body=body)


@router.get("/", response_model=list[MatchOut])
async def list_matches(
    Authorization: str = Header(default=None),
):
    """List all matches where the current user is creator or player."""
    kinde_user_id, _, _ = _kinde_identity(Authorization)
    return MatchService().list_matches(kinde_user_id=kinde_user_id)


@router.get("/{match_id}", response_model=MatchOut)
async def get_match(
    match_id: uuid.UUID,
    Authorization: str = Header(default=None),
):
    """Get a single match with players and scores."""
    _kinde_identity(Authorization)
    match = MatchService().get_match(match_id=match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match


@router.patch("/{match_id}/split", response_model=MatchOut)
async def split_match(
    match_id: uuid.UUID,
    body: MatchSplit,
    Authorization: str = Header(default=None),
):
    """Record total cost and trigger Splitwise expense. Only the match creator can do this."""
    kinde_user_id, _, _ = _kinde_identity(Authorization)
    match = await MatchService().split_match(
        match_id=match_id, created_by=kinde_user_id, total_cost=body.total_cost
    )
    if not match:
        raise HTTPException(status_code=403, detail="Match not found or not authorised")
    return match
