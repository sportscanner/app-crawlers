
# """Geoapify MCP Server implementation using FastMCP and streamable HTTP."""

import asyncio
from sportscanner.logger import logging
from fastmcp import FastMCP
from fastmcp.server.auth import OIDCProxy
from fastmcp.tools import Tool

from sportscanner.mcp.auth import HybridTokenVerifier
from sportscanner.mcp.registry import TOOL_FUNCTIONS
from sportscanner.variables import settings

# Kinde doesn't support Dynamic Client Registration yet, which is required for
# Claude web (and other MCP clients) to self-register against an OAuth server.
# OIDCProxy fronts Kinde with one pre-registered upstream client (the existing
# frontend app, which is a public/PKCE client, so no client_secret here) and
# fakes DCR for downstream clients. See `sportscanner/mcp/auth.py` for how
# legacy personal API tokens (`ssc_...`) keep working alongside this.
auth = OIDCProxy(
    config_url=f"{settings.KINDE_DOMAIN}/.well-known/openid-configuration",
    client_id=settings.KINDE_CLIENT_ID,
    base_url=settings.MCP_PUBLIC_BASE_URL,
    token_verifier=HybridTokenVerifier(),
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