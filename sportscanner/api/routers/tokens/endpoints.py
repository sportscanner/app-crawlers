"""
Personal API token management.

Mounted at `/user/tokens`. Authentication uses the same Kinde refresh-token
header contract as the rest of the `/user` endpoints — the frontend passes the
Kinde refresh token in the `Authorization` header. The tokens minted here are a
*separate* credential used to authenticate the MCP server / public API.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Path
from starlette import status
from starlette.requests import Request

import sportscanner.storage.postgres.database as db
from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details
from sportscanner.storage.postgres.api_token_repository import ApiTokenRepository
from sportscanner.storage.postgres.tables import ApiToken

router = APIRouter()
repo = ApiTokenRepository(db.engine)

# Cap token lifetime so "temporary" stays temporary.
MAX_EXPIRY_DAYS = 365


async def _kinde_user_id(refresh_token: Optional[str]) -> str:
    access_token = await get_kinde_access_token(refresh_token=refresh_token)
    return (await get_kinde_user_details(access_token))["id"]


def _serialize(token: ApiToken) -> dict:
    now = datetime.utcnow()
    return {
        "id": token.id,
        "name": token.name,
        "prefix": token.token_prefix,
        "createdAt": token.created_at,
        "expiresAt": token.expires_at,
        "lastUsedAt": token.last_used_at,
        "revoked": token.revoked,
        "expired": bool(token.expires_at and token.expires_at < now),
    }


@router.get("/", status_code=status.HTTP_200_OK)
async def list_tokens(Authorization: str = Header(default=None)):
    """List the caller's API tokens (metadata only — never the raw secret)."""
    user_id = await _kinde_user_id(Authorization)
    return [_serialize(token) for token in repo.list_for_user(user_id)]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_token(request: Request, Authorization: str = Header(default=None)):
    """
    Create a token. Body: `{ "name": str, "expiresInDays": int | null }`.
    The raw `token` is returned exactly once in this response.
    """
    body = await request.json()
    user_id = await _kinde_user_id(Authorization)

    name = (body.get("name") or "API token").strip()[:60] or "API token"

    expires_at: Optional[datetime] = None
    expires_in_days = body.get("expiresInDays")
    if expires_in_days is not None:
        try:
            days = int(expires_in_days)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="expiresInDays must be an integer")
        if days <= 0:
            raise HTTPException(status_code=400, detail="expiresInDays must be positive")
        days = min(days, MAX_EXPIRY_DAYS)
        expires_at = datetime.utcnow() + timedelta(days=days)

    raw, token = repo.create(user_id, name, expires_at)
    return {"token": raw, **_serialize(token)}


@router.delete("/{token_id}", status_code=status.HTTP_200_OK)
async def revoke_token(
    token_id: str = Path(..., description="Token id to revoke"),
    Authorization: str = Header(default=None),
):
    user_id = await _kinde_user_id(Authorization)
    if not repo.revoke(user_id, token_id):
        raise HTTPException(status_code=404, detail="Token not found")
    return {"success": True}
