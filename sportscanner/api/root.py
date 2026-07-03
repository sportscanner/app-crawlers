import json
from datetime import datetime
from typing import List

from fastapi import FastAPI, Header, Path, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.requests import Request

from sportscanner.api.routers.geolocation.endpoints import router as GeolocationRouter
from sportscanner.api.routers.search.endpoints import (
    router as SearchRouter,
)

from sportscanner.api.routers.users.endpoints import router as UsersRouter
from sportscanner.api.routers.venues.endpoints import router as VenuesRouter
from sportscanner.api.routers.health.endpoints import router as HealthRouter
from sportscanner.api.routers.notifications.endpoints import router as NotificationsRouter
from sportscanner.api.routers.tokens.endpoints import router as TokensRouter

from sportscanner.logger import logging
from sportscanner.storage.postgres.api_token_repository import ApiTokenRepository
import sportscanner.storage.postgres.database as db
from starlette.responses import JSONResponse

import httpx


# ── MCP server (optional dependency: fastmcp) ────────────────────────────────
# The MCP layer is mounted into this same FastAPI app so the REST API and the
# MCP server ship as a single deployment. Requests to /mcp are authenticated
# with personal API tokens (see _McpTokenAuth below). Import is defensive: a
# missing/incompatible fastmcp must never take the core API down.
_mcp_app = None
try:
    from sportscanner.mcp.server import mcp as _sportscanner_mcp

    # stateless_http=True: each request is self-contained, so clients don't need
    # the initialize -> Mcp-Session-Id -> call handshake. Our tools are simple
    # request/response (geocoding, DB lookups) with no session state or
    # server-push, so a plain `curl … tools/list` works. Standard MCP clients
    # (Claude Desktop via mcp-remote, Cursor) remain compatible.
    _mcp_app = _sportscanner_mcp.http_app(path="/", stateless_http=True)
except Exception as exc:  # pragma: no cover - defensive
    logging.warning(f"MCP server not mounted (fastmcp unavailable?): {exc}")


class _McpTokenAuth:
    """
    Raw-ASGI wrapper that gates the mounted MCP app behind a personal API token.

    Implemented at the ASGI layer (rather than BaseHTTPMiddleware) so it only
    inspects request headers and never buffers the MCP streaming/SSE responses.
    """

    def __init__(self, app):
        self.app = app
        self._repo = ApiTokenRepository(db.engine)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            authorization = headers.get(b"authorization", b"").decode() or None
            kinde_user_id = self._repo.authenticate(authorization)
            if not kinde_user_id:
                response = JSONResponse(
                    {
                        "error": "invalid_or_missing_api_token",
                        "detail": "Provide a valid Sportscanner API token via 'Authorization: Bearer <token>'.",
                    },
                    status_code=401,
                )
                await response(scope, receive, send)
                return
            scope.setdefault("state", {})
            scope["state"]["kinde_user_id"] = kinde_user_id
        await self.app(scope, receive, send)


class _McpTrailingSlashMiddleware:
    """
    Rewrite a bare `/mcp` request to `/mcp/` before routing.

    The MCP app is mounted at `/mcp`, so Starlette only matches `/mcp/…` and a
    bare `/mcp` would be answered with a 307 redirect to `/mcp/`. Several MCP
    clients mishandle that redirect on POST (they drop the body/method), so we
    rewrite the path at the ASGI layer — ahead of the router — and serve it
    directly. Runs as raw ASGI so it never buffers the MCP streaming responses.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == "/mcp":
            scope = dict(scope)
            scope["path"] = "/mcp/"
            raw_path = scope.get("raw_path")
            if raw_path is not None and not raw_path.endswith(b"/"):
                scope["raw_path"] = raw_path + b"/"
        await self.app(scope, receive, send)


description = """
## Sportscanner API

This aggregator API is a comprehensive platform designed to help sports enthusiasts find and book badminton, squash, and pickleball courts across London with ease.

You will be able to:

* Search for Badminton, Squash and Pickleball court bookings across London
* Find Venues near you that offers different types of sports, and amneties
* Compare prices, facilities, and peak/off-peak times. Book directly through venue links
"""

app = FastAPI(
    title="Sportscanner",
    description=description,
    summary="Find Badminton, Squash, and Pickleball facilities; and available courts for hire across London",
    version="1.0.0",
    contact={
        "name": "Sportscanner (dev)",
        "url": "https://www.linkedin.com/company/sportscanner/",
        "email": "info@sportscanner.co.uk",
    },
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
    # FastMCP's streamable-HTTP app needs its lifespan to run so the session
    # manager is initialised; wiring it here lets us mount it below.
    lifespan=_mcp_app.lifespan if _mcp_app is not None else None,
)

# Serve /mcp (no trailing slash) directly instead of 307-redirecting to /mcp/.
app.add_middleware(_McpTrailingSlashMiddleware)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace '*' with specific origins if needed
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

app.include_router(
    router=SearchRouter, prefix="/search", tags=["Search"]
)

app.include_router(router=VenuesRouter, prefix="/venues", tags=["Venues"])

app.include_router(
    router=GeolocationRouter, prefix="/geolocation", tags=["Geolocation"]
)

app.include_router(router=UsersRouter, prefix="/user", tags=["internal"], include_in_schema=False)

app.include_router(router=TokensRouter, prefix="/user/tokens", tags=["Developer"], include_in_schema=False)

app.include_router(router=HealthRouter, prefix="/health", tags=["Health"])

app.include_router(
    router=NotificationsRouter,
    prefix="/notifications",
    tags=["Notifications"],
)

# Mount the token-authenticated MCP server at /mcp (single deployment).
if _mcp_app is not None:
    app.mount("/mcp", _McpTokenAuth(_mcp_app))
    logging.info("Sportscanner MCP server mounted at /mcp")

@app.get("/", tags=["Root"])
async def root():
    """Root API landing page (should be deployed at api.domain.com)"""
    return {
        "timestamp": datetime.now(),
        "message": "Welcome to the Sportscanner API",
        "version": "v1.3.0",
        "actions": {
            "/search/": "Endpoint to find available sports bookings",
            "/venue/": "Endpoint to find Venues covered by Sportscanner monitoring",
            "/docs": "Documentation for API endpoints",
        },
    }
