"""
Connected MCP agents (Claude, Cursor, etc.) - list and revoke.

Mounted at `/user/mcp-connections`. Same Kinde refresh-token header contract
as `/user/tokens` (see that router). These are legacy records: the public
MCP server no longer accepts or issues OAuth grants.
"""

from fastapi import APIRouter, Header, HTTPException, Path
from starlette import status

import sportscanner.storage.postgres.database as db
from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details
from sportscanner.storage.postgres.mcp_client_repository import (
    McpAuthorizedClientRepository,
)

router = APIRouter()
repo = McpAuthorizedClientRepository(db.engine)


def _kinde_user_id(refresh_token):
    access_token = get_kinde_access_token(refresh_token=refresh_token)
    return get_kinde_user_details(access_token)["id"]


@router.get("/", status_code=status.HTTP_200_OK)
async def list_connections(Authorization: str = Header(default=None)):
    """List the caller's authorized MCP clients."""
    user_id = _kinde_user_id(Authorization)
    return [
        {
            "id": row.id,
            "clientName": row.client_name,
            "createdAt": row.created_at,
        }
        for row in repo.list_for_user(user_id)
    ]


@router.delete("/{connection_id}", status_code=status.HTTP_200_OK)
async def revoke_connection(
    connection_id: str = Path(..., description="Connection id to revoke"),
    Authorization: str = Header(default=None),
):
    user_id = _kinde_user_id(Authorization)
    row = repo.get_owned(user_id, connection_id)
    if not row:
        raise HTTPException(status_code=404, detail="Connection not found")

    # The public MCP server no longer accepts any OAuth grants. Retain this
    # authenticated endpoint so users can remove legacy connection records.
    repo.revoke(user_id, connection_id)
    return {"success": True}
