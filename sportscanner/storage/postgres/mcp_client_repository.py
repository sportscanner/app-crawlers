"""
Repository for tracking which OAuth clients (Claude, Cursor, etc.) a user has
authorized for the MCP server, so they can see and revoke them later. See
`sportscanner.mcp.oidc_proxy.TrackingOIDCProxy` for where rows get created and
how revocation actually invalidates the underlying grant.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from sqlmodel import Session, select

from sportscanner.storage.postgres.tables import McpAuthorizedClient


class McpAuthorizedClientRepository:
    def __init__(self, engine):
        self.engine = engine

    def record(
        self,
        kinde_user_id: str,
        client_id: str,
        client_name: str,
        access_jti: str,
        refresh_jti: Optional[str],
    ) -> McpAuthorizedClient:
        row = McpAuthorizedClient(
            id=uuid.uuid4().hex,
            kinde_user_id=kinde_user_id,
            client_id=client_id,
            client_name=client_name,
            access_jti=access_jti,
            refresh_jti=refresh_jti,
        )
        with Session(self.engine) as session:
            session.add(row)
            session.commit()
            session.refresh(row)
        return row

    def list_for_user(self, kinde_user_id: str) -> List[McpAuthorizedClient]:
        with Session(self.engine) as session:
            statement = (
                select(McpAuthorizedClient)
                .where(McpAuthorizedClient.kinde_user_id == kinde_user_id)
                .where(McpAuthorizedClient.revoked == False)  # noqa: E712
                .order_by(McpAuthorizedClient.created_at.desc())
            )
            return list(session.exec(statement))

    def get_owned(self, kinde_user_id: str, connection_id: str) -> Optional[McpAuthorizedClient]:
        with Session(self.engine) as session:
            row = session.get(McpAuthorizedClient, connection_id)
            if not row or row.kinde_user_id != kinde_user_id or row.revoked:
                return None
            return row

    def revoke(self, kinde_user_id: str, connection_id: str) -> bool:
        with Session(self.engine) as session:
            row = session.get(McpAuthorizedClient, connection_id)
            if not row or row.kinde_user_id != kinde_user_id:
                return False
            row.revoked = True
            session.add(row)
            session.commit()
            return True
