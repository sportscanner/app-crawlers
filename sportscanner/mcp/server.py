
# """Geoapify MCP Server implementation using FastMCP and streamable HTTP."""

import asyncio
from mcp.types import Icon
from sportscanner.logger import logging
from fastmcp import FastMCP
from fastmcp.tools import Tool

import sportscanner.storage.postgres.database as db
from sportscanner.mcp import branding
from sportscanner.mcp.auth import HybridTokenVerifier
from sportscanner.mcp.oidc_proxy import TrackingOIDCProxy
from sportscanner.mcp.registry import TOOL_FUNCTIONS
from sportscanner.storage.postgres.mcp_client_repository import McpAuthorizedClientRepository
from sportscanner.variables import settings

# Re-skins the OAuth consent/error pages (colors, font) to match the
# Sportscanner brand; see branding.py for why this is a best-effort patch
# rather than an official API.
branding.apply()


def _build_client_storage():
    """Back the OAuth proxy's session state with Valkey when configured, so
    grants survive a Render redeploy (the library's own default is a local
    file store, which doesn't). Falls back to that library default (fine for
    local dev) when VALKEY_URL is unset, matching the existing "cache is
    optional" pattern in sportscanner/cache.py."""
    if not settings.VALKEY_URL:
        return None
    try:
        import redis.asyncio as redis_asyncio
        from cryptography.fernet import Fernet
        from key_value.aio.stores.redis import RedisStore
        from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
        from fastmcp.server.auth.jwt_issuer import derive_jwt_key

        encryption_key = derive_jwt_key(
            high_entropy_material=settings.JWT_SECRET,
            salt="sportscanner-mcp-oauth-storage",
        )
        # RedisStore(url=...) manually parses the URL and ignores the
        # rediss:// scheme entirely (never enables TLS), unlike the sync
        # redis.from_url() this project already relies on in cache.py.
        # Building the client ourselves via Redis.from_url() sidesteps that
        # library bug and matches the sync client's proven-working TLS setup.
        redis_client = redis_asyncio.Redis.from_url(settings.VALKEY_URL, decode_responses=True)
        return FernetEncryptionWrapper(
            key_value=RedisStore(client=redis_client),
            fernet=Fernet(key=encryption_key),
            raise_on_decryption_error=False,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logging.warning(f"MCP OAuth storage: falling back to local file store ({exc})")
        return None


# Kinde doesn't support Dynamic Client Registration yet, which is required for
# Claude web (and other MCP clients) to self-register against an OAuth server.
# OIDCProxy fronts Kinde with one pre-registered upstream client (the existing
# frontend app, which is a public/PKCE client, so no client_secret here) and
# fakes DCR for downstream clients. See `sportscanner/mcp/auth.py` for how
# legacy personal API tokens (`ssc_...`) keep working alongside this.
# TrackingOIDCProxy additionally records each new authorization so users can
# see and revoke connected clients - see `sportscanner/mcp/oidc_proxy.py`.
auth = TrackingOIDCProxy(
    config_url=f"{settings.KINDE_DOMAIN}/.well-known/openid-configuration",
    client_id=settings.KINDE_CLIENT_ID,
    base_url=settings.MCP_PUBLIC_BASE_URL,
    token_verifier=HybridTokenVerifier(),
    client_storage=_build_client_storage(),
    client_repository=McpAuthorizedClientRepository(db.engine),
    # OIDCProxy signs its own downstream session tokens (separate from Kinde's
    # tokens); required whenever no upstream client_secret is provided. Reuses
    # the existing (currently otherwise-unused) JWT_SECRET rather than adding
    # a new secret to provision.
    jwt_signing_key=settings.JWT_SECRET,
    allowed_client_redirect_uris=[
        "https://claude.ai/api/mcp/auth_callback",
        "http://localhost/callback",
        "http://127.0.0.1/callback",
    ],
)

mcp = FastMCP(
    name="Sportscanner Unified MCP",
    tools=[func for func in TOOL_FUNCTIONS.values()],
    auth=auth,
    website_url="https://www.sportscanner.co.uk",
    icons=[Icon(src="https://www.sportscanner.co.uk/sportscanner.svg")],
)

'''Following code block doesn't register tools with some clients like DeepChat'''
# Register each function as a tool (loop over your dict for convenience)
# for tool_name, func in TOOL_FUNCTIONS.items():
#     tool = Tool.from_function(func, name=tool_name)
#     mcp.add_tool(tool)

if __name__ == "__main__":
    async def list_tools():
        tools = await mcp.get_tools()  # Or mcp.list_tools() in older versions
        print("Registered tools:", [tool.name for tool in tools.values()])  # Use .values() for Tool objects
    asyncio.run(list_tools())
    mcp.run(transport="http", port=8080)  # Change 8080 to your desired port