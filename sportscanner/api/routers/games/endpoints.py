import uuid
from typing import Optional

from fastapi import APIRouter, Header, status

from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details

from .schemas import GameCreate, GameListOut, GameOut, JoinGameOut
from .service.gameService import GameService

router = APIRouter()


def _get_user_id(Authorization: str) -> str:
    access_token = get_kinde_access_token(refresh_token=Authorization)
    user_details = get_kinde_user_details(access_token)
    return user_details["id"]


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


@router.get("/{game_id}", response_model=GameOut)
async def get_game(game_id: uuid.UUID):
    """Game detail with participants. Public — no auth required to view."""
    return GameService().get_game(game_id)


@router.post("/{game_id}/join", response_model=JoinGameOut)
async def join_game(
    game_id: uuid.UUID,
    Authorization: str = Header(default=None, title="Bearer token to authenticate user"),
):
    """Starts a payment to join a game — returns a PaymentIntent client_secret for
    the frontend to confirm with Stripe.js (card, Apple Pay, and Google Pay all
    surface automatically via the PaymentElement)."""
    user_id = _get_user_id(Authorization)
    return GameService().join_game(game_id, user_id)


@router.post("/{game_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_game(
    game_id: uuid.UUID,
    Authorization: str = Header(default=None, title="Bearer token to authenticate user"),
):
    """Organizer-only: cancels the game and refunds every paid participant in full."""
    user_id = _get_user_id(Authorization)
    GameService().cancel_game(game_id, user_id)
