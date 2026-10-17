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
from sportscanner.api.routers.games.endpoints import router as GamesRouter
from sportscanner.api.routers.health.endpoints import router as HealthRouter
from sportscanner.api.routers.notifications.endpoints import (
    router as NotificationsRouter,
)
from sportscanner.api.routers.tokens.endpoints import router as TokensRouter
from sportscanner.api.routers.mcp_connections.endpoints import (
    router as McpConnectionsRouter,
)

from sportscanner.logger import logging
from sportscanner.api.routers.discovery.endpoints import create_router, discovery_links
from sportscanner.variables import settings

import httpx

# MCP shares this deployment but exposes only public, read-only tools.
# Account routes keep their own Kinde authentication. Import defensively so
# a missing/incompatible optional FastMCP dependency cannot take REST down.
_mcp_app = None
try:
    from sportscanner.mcp.server import mcp as _sportscanner_mcp

    # stateless_http=True: each request is self-contained, so clients don't need
    # the initialize -> Mcp-Session-Id -> call handshake. Our tools are simple
    # request/response (geocoding, DB lookups) with no session state or
    # server-push, so a plain `curl … tools/list` works. Standard MCP clients
    # (Claude Desktop via mcp-remote, Cursor) remain compatible.
    _mcp_app = _sportscanner_mcp.http_app(path="/mcp", stateless_http=True)
except Exception as exc:  # pragma: no cover - defensive
    logging.warning(f"MCP server not mounted (fastmcp unavailable?): {exc}")


description = """
## Sportscanner API

Find publicly available badminton, squash, pickleball, padel and tennis courts across London.

You will be able to:

* Search court availability by sport, postcode, date, time, distance and price. Search and venue lookup require no authentication.
* Find nearby venues and compare GBP prices. Times use Europe/London.
* Follow provider booking links. SportScanner does not reserve courts or process payments.
* Read /agents.md for request examples, freshness guidance and MCP setup.
"""

app = FastAPI(
    title="Sportscanner",
    description=description,
    summary="Find badminton, squash, pickleball, padel and tennis courts across London",
    version="1.0.0",
    servers=[{"url": settings.MCP_PUBLIC_BASE_URL.rstrip("/")}],
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

@app.middleware("http")
async def agent_discovery_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/":
        response.headers.append("Link", discovery_links(settings.MCP_PUBLIC_BASE_URL.rstrip("/")))
    return response


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace '*' with specific origins if needed
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

app.include_router(router=SearchRouter, prefix="/search", tags=["Search"])

app.include_router(router=VenuesRouter, prefix="/venues", tags=["Venues"])

app.include_router(router=GamesRouter, prefix="/games", tags=["Games"])

app.include_router(
    router=GeolocationRouter, prefix="/geolocation", tags=["Geolocation"]
)

app.include_router(
    router=UsersRouter, prefix="/user", tags=["internal"], include_in_schema=False
)

app.include_router(
    router=TokensRouter,
    prefix="/user/tokens",
    tags=["Developer"],
    include_in_schema=False,
)

app.include_router(
    router=McpConnectionsRouter,
    prefix="/user/mcp-connections",
    tags=["Developer"],
    include_in_schema=False,
)

app.include_router(router=HealthRouter, prefix="/health", tags=["Health"])
app.include_router(create_router(settings.MCP_PUBLIC_BASE_URL, _mcp_app is not None))

app.include_router(
    router=NotificationsRouter,
    prefix="/notifications",
    tags=["Notifications"],
)


@app.get("/", tags=["Root"])
async def root():
    """Root API landing page (should be deployed at api.domain.com)"""
    return {
        "timestamp": datetime.now(),
        "message": "Welcome to the Sportscanner API",
        "version": "v1.3.0",
        "actions": {
            "/search/{sport}": "POST court search with date query and JSON filters",
            "/venues/": "Venues covered by Sportscanner monitoring",
            "/docs": "Documentation for API endpoints",
            "/agents.md": "Public search instructions and MCP setup for agents",
            "/.well-known/api-catalog": "Machine-readable API discovery",
        },
    }


# Mount last so REST, docs and discovery routes take precedence. FastMCP
# handles the public /mcp endpoint; it does not publish OAuth routes.
if _mcp_app is not None:
    app.mount("/", _mcp_app)
    logging.info("Sportscanner MCP server mounted (JSON-RPC endpoint at /mcp)")
