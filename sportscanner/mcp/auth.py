"""
Token verification for the Sportscanner MCP server.

Two credential types are accepted on the same `/mcp` mount:
- Legacy personal API tokens (`ssc_...`), minted via `/user/tokens` and used
  today by Claude Desktop/Cursor through `mcp-remote`.
- Kinde-issued OAuth access tokens, obtained via the OIDCProxy flow (used by
  Claude web and any other client that speaks OAuth 2.1 + PKCE).
"""

from fastmcp.server.auth import AccessToken, JWTVerifier, TokenVerifier
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration

import sportscanner.storage.postgres.database as db
from sportscanner.logger import logging
from sportscanner.storage.postgres.api_token_repository import ApiTokenRepository, TOKEN_PREFIX
from sportscanner.variables import settings


class HybridTokenVerifier(TokenVerifier):
    """Accepts either a legacy `ssc_` personal API token or a Kinde OAuth token."""

    def __init__(self):
        super().__init__()
        self._legacy_tokens = ApiTokenRepository(db.engine)
        oidc_config = OIDCConfiguration.get_oidc_configuration(
            f"{settings.KINDE_DOMAIN}/.well-known/openid-configuration",
            strict=None,
            timeout_seconds=None,
        )
        self._jwt_verifier = JWTVerifier(
            jwks_uri=str(oidc_config.jwks_uri),
            issuer=str(oidc_config.issuer),
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        if token.startswith(TOKEN_PREFIX):
            kinde_user_id = self._legacy_tokens.authenticate(token)
            if kinde_user_id is None:
                return None
            return AccessToken(
                token=token,
                client_id=kinde_user_id,
                scopes=[],
            )
        try:
            return await self._jwt_verifier.verify_token(token)
        except Exception:
            logging.warning("MCP: failed to verify token as Kinde OAuth token")
            return None
