"""
Repository for personal API tokens.

Tokens are used both for the (future) public REST API and, today, to
authenticate the Sportscanner MCP server. A token belongs to exactly one
Kinde user account. We store only a SHA-256 hash of the token — the raw
value is returned to the caller once at creation time and never again.
"""

import hashlib
import secrets
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

from sqlmodel import Session, select

from sportscanner.storage.postgres.tables import ApiToken

TOKEN_PREFIX = "ssc_"


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _strip_bearer(value: str) -> str:
    value = value.strip()
    if value.lower().startswith("bearer "):
        return value.split(" ", 1)[1].strip()
    return value


class ApiTokenRepository:
    def __init__(self, engine):
        self.engine = engine

    def create(
        self,
        kinde_user_id: str,
        name: str,
        expires_at: Optional[datetime] = None,
    ) -> Tuple[str, ApiToken]:
        """Generate a new token; returns (raw_token, persisted_metadata)."""
        raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
        token = ApiToken(
            id=uuid.uuid4().hex,
            kinde_user_id=kinde_user_id,
            name=(name or "API token").strip()[:60] or "API token",
            token_prefix=raw[:11],
            token_hash=_hash_token(raw),
            expires_at=expires_at,
        )
        with Session(self.engine) as session:
            session.add(token)
            session.commit()
            session.refresh(token)
        return raw, token

    def list_for_user(self, kinde_user_id: str) -> List[ApiToken]:
        with Session(self.engine) as session:
            statement = (
                select(ApiToken)
                .where(ApiToken.kinde_user_id == kinde_user_id)
                .order_by(ApiToken.created_at.desc())
            )
            return list(session.exec(statement))

    def revoke(self, kinde_user_id: str, token_id: str) -> bool:
        """Revoke a token the user owns. Returns False if not found/owned."""
        with Session(self.engine) as session:
            token = session.get(ApiToken, token_id)
            if not token or token.kinde_user_id != kinde_user_id:
                return False
            token.revoked = True
            session.add(token)
            session.commit()
            return True

    def authenticate(self, raw_authorization: Optional[str]) -> Optional[str]:
        """
        Resolve a raw token (optionally 'Bearer '-prefixed) to a kinde_user_id.
        Returns None when the token is missing, unknown, revoked or expired.
        Updates last_used_at on success.
        """
        if not raw_authorization:
            return None
        raw = _strip_bearer(raw_authorization)
        if not raw:
            return None
        token_hash = _hash_token(raw)
        with Session(self.engine) as session:
            token = session.exec(
                select(ApiToken).where(ApiToken.token_hash == token_hash)
            ).first()
            if not token or token.revoked:
                return None
            if token.expires_at and token.expires_at < datetime.utcnow():
                return None
            token.last_used_at = datetime.utcnow()
            session.add(token)
            session.commit()
            return token.kinde_user_id
