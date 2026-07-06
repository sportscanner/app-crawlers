"""
OIDCProxy subclass that tracks which clients (Claude, Cursor, etc.) get
authorized, so users can see and revoke them from the developer console.

Overrides `exchange_authorization_code` - the point a new authorization
completes - to record a row via `McpAuthorizedClientRepository`. Revocation
(`revoke_grant`) deletes the corresponding `_jti_mapping_store` entries;
`load_access_token` and `exchange_refresh_token` both look up that store on
every call and fail closed if the entry is missing, so this takes effect
immediately rather than only on next refresh. See the plan/investigation notes
for why this is the low-risk override point (a public MCP SDK provider
method, not a private helper) and what happens if fastmcp changes its shape.
"""

import jwt
from mcp.server.auth.provider import AuthorizationCode
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from fastmcp.server.auth import OIDCProxy

from sportscanner.logger import logging
from sportscanner.storage.postgres.mcp_client_repository import McpAuthorizedClientRepository


def _decode_claim_without_verification(token: str, claim: str) -> str | None:
    """Best-effort claim extraction from a JWT we already trust (it just came
    from our own successful server-to-server exchange, or is our own signed
    token) - never raises, so a malformed/unexpected token shape only skips
    tracking rather than blocking a real login."""
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        return payload.get(claim)
    except Exception:
        return None


class TrackingOIDCProxy(OIDCProxy):
    def __init__(self, *args, client_repository: McpAuthorizedClientRepository, **kwargs):
        super().__init__(*args, **kwargs)
        self._client_repository = client_repository

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        code_model = await self._code_store.get(key=authorization_code.code)
        idp_access_token = (
            code_model.idp_tokens.get("access_token") if code_model else None
        )

        token = await super().exchange_authorization_code(client, authorization_code)

        try:
            if not idp_access_token or not client.client_id:
                return token
            kinde_user_id = _decode_claim_without_verification(idp_access_token, "sub")
            if not kinde_user_id:
                return token

            access_jti = _decode_claim_without_verification(token.access_token, "jti")
            refresh_jti = (
                _decode_claim_without_verification(token.refresh_token, "jti")
                if token.refresh_token
                else None
            )
            if not access_jti:
                return token

            client_name = getattr(client, "client_name", None) or client.client_id
            self._client_repository.record(
                kinde_user_id=kinde_user_id,
                client_id=client.client_id,
                client_name=client_name,
                access_jti=access_jti,
                refresh_jti=refresh_jti,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logging.warning(f"MCP: failed to record authorized client (login still succeeds): {exc}")

        return token

    async def revoke_grant(self, access_jti: str, refresh_jti: str | None) -> None:
        await self._jti_mapping_store.delete(key=access_jti)
        if refresh_jti:
            await self._jti_mapping_store.delete(key=refresh_jti)
