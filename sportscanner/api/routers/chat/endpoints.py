from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel
from stream_chat import StreamChat

from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details
from sportscanner.storage.postgres.database import engine
from sportscanner.storage.postgres.user_repository import PostgresUserRepository
from sportscanner.variables import settings

router = APIRouter()


def _require_stream_client() -> StreamChat:
    if not settings.STREAM_API_KEY or not settings.STREAM_API_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat is not configured. STREAM_API_KEY and STREAM_API_SECRET must be set.",
        )
    return StreamChat(api_key=settings.STREAM_API_KEY, api_secret=settings.STREAM_API_SECRET)


def _kinde_identity(refresh_token: str) -> tuple[str, str, str]:
    """Returns (kinde_user_id, full_name, email) from a refresh token."""
    access_token = get_kinde_access_token(refresh_token=refresh_token)
    d = get_kinde_user_details(access_token)
    full_name = f"{d.get('first_name', '')} {d.get('last_name', '')}".strip()
    return d["id"], full_name, d.get("preferred_email", "")


@router.get("/token", status_code=status.HTTP_200_OK)
async def get_chat_token(Authorization: str = Header(default=None)):
    """
    Generate a Stream Chat user token for the authenticated user.
    The frontend uses this token to connect directly to Stream.
    """
    user_id, full_name, email = _kinde_identity(Authorization)
    client = _require_stream_client()

    # Upsert the user in Stream so their display name is always current.
    client.upsert_user({"id": user_id, "name": full_name, "email": email})

    token = client.create_token(user_id)
    return {"token": token, "user_id": user_id, "name": full_name}


class CreateChannelRequest(BaseModel):
    other_user_id: str  # Kinde user ID of the person to chat with


@router.post("/channel", status_code=status.HTTP_200_OK)
async def create_or_get_channel(
    body: CreateChannelRequest,
    Authorization: str = Header(default=None),
):
    """
    Create (or retrieve) a direct-message channel between the current user and another user.
    Uses a deterministic channel ID based on sorted user IDs so the same two users
    always land in the same channel regardless of who initiates.
    """
    user_id, _, _ = _kinde_identity(Authorization)
    client = _require_stream_client()

    # Ensure the other user exists in Stream before adding them to a channel.
    repo = PostgresUserRepository(engine)
    other_user = repo.get_user(body.other_user_id)
    if not other_user:
        raise HTTPException(status_code=404, detail="Target user not found")

    client.upsert_user({
        "id": other_user.kinde_user_id,
        "name": other_user.full_name or "",
        "email": other_user.email,
    })

    # Deterministic channel ID: alphabetically sorted user IDs joined by "--".
    # Trimmed to 64 chars (Stream limit).
    members = sorted([user_id, body.other_user_id])
    channel_id = f"dm--{'--'.join(members)}"[:64]

    channel = client.channel(
        "messaging",
        channel_id,
        {"members": members},
    )
    channel.create(user_id)

    return {"channel_id": channel_id, "channel_type": "messaging"}
