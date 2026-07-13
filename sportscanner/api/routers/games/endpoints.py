import uuid
from typing import Optional

from fastapi import APIRouter, Header, Request, status

from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details
from sportscanner.core.rate_limit import limiter

from .schemas import CancelGameOut, GameCreate, GameDetailOut, GameListOut, GameOut, JoinGameOut
from .service.gameService import GameService

router = APIRouter()


def _get_user_id(Authorization: str) -> str:
    access_token = get_kinde_access_token(refresh_token=Authorization)
    user_details = get_kinde_user_details(access_token)
    return user_details["id"]


def _get_user_id_optional(Authorization: Optional[str]) -> Optional[str]:
    """Best-effort identity resolution for endpoints that are public but adapt
    their response when the caller happens to be authenticated (e.g. showing
    is_organizer). A missing or invalid token is treated as anonymous rather
    than a 401 — the endpoint itself never requires auth."""
    if not Authorization:
        return None
    try:
        return _get_user_id(Authorization)
    except Exception:
        return None


@router.post("/", response_model=GameOut, status_code=status.HTTP_201_CREATED)
async def create_game(
    body: GameCreate,
    Authorization: str = Header(default=None, title="Bearer token to authenticate user"),
):
    """Organize a new game. Requires a connected + charges-enabled Stripe account."""
    user_id = _get_user_id(Authorization)
    return GameService().create_game(user_id, body)


@router.get("/", response_model=list[GameListOut])
async def list_games(sport: Optional[str] = None):
    """Browse open, upcoming games. Public — no auth required to browse."""
    return GameService().list_open_games(sport)


@router.get("/mine", response_model=list[GameOut])
async def list_my_games(
    Authorization: str = Header(default=None, title="Bearer token to authenticate user"),
):
    """Games the current user organizes, with full participant detail (for managing/cancelling)."""
    user_id = _get_user_id(Authorization)
    return GameService().list_my_games(user_id)


@router.get("/{game_id}", response_model=GameDetailOut)
async def get_game(
    game_id: uuid.UUID,
    Authorization: Optional[str] = Header(default=None, title="Optional bearer token"),
):
    """Public game detail — auth is optional and only used to compute `is_organizer`
    for the caller's own game. Deliberately excludes organizer_id and per-participant
    user_id/amount_pence/raw email; see GameDetailOut."""
    viewer_id = _get_user_id_optional(Authorization)
    return GameService().get_game(game_id, viewer_id)


@router.post("/{game_id}/join", response_model=JoinGameOut)
@limiter.limit("10/minute")
async def join_game(
    request: Request,
    game_id: uuid.UUID,
    Authorization: str = Header(default=None, title="Bearer token to authenticate user"),
):
    """Starts a payment to join a game — returns a PaymentIntent client_secret for
    the frontend to confirm with Stripe.js (card, Apple Pay, and Google Pay all
    surface automatically via the PaymentElement). Rate-limited per IP — this
    endpoint creates real Stripe PaymentIntents, making it a card-testing target."""
    user_id = _get_user_id(Authorization)
    return GameService().join_game(game_id, user_id)


@router.post("/{game_id}/cancel", response_model=CancelGameOut)
async def cancel_game(
    game_id: uuid.UUID,
    Authorization: str = Header(default=None, title="Bearer token to authenticate user"),
):
    """Organizer-only: cancels the game and refunds every paid participant in full.
    The game is marked cancelled regardless of individual refund outcomes — check
    `failed_participant_ids` for any that need manual follow-up in the Stripe dashboard."""
    user_id = _get_user_id(Authorization)
    return GameService().cancel_game(game_id, user_id)
