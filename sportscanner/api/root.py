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
from sportscanner.api.routers.mcp_connections.endpoints import router as McpConnectionsRouter

from sportscanner.logger import logging

import httpx


# ── MCP server (optional dependency: fastmcp) ────────────────────────────────
# The MCP layer is mounted into this same FastAPI app so the REST API and the
# MCP server ship as a single deployment. Auth (personal API tokens and Kinde
# OAuth) is enforced inside the FastMCP app itself via its `auth=` provider
# (see sportscanner/mcp/server.py). Import is defensive: a missing/incompatible
# fastmcp must never take the core API down.
#
# The FastMCP app is mounted at the FastAPI app's true root (not under /mcp),
# with its own internal MCP endpoint path set to "/mcp" (so the externally
# visible URL is unchanged: https://api.sportscanner.co.uk/mcp). This matters
# for OAuth: RFC 9728 requires protected-resource metadata to be served at
# `{origin}/.well-known/oauth-protected-resource{resource_path}` — a fixed
# location FastMCP computes from `base_url`/`resource_path` alone, with no
# awareness of an extra outer mount prefix. Nesting the FastMCP app under an
# additional "/mcp" Mount (as before) made that metadata route only reachable
# at "/mcp/.well-known/..." — a path Claude (and any spec-compliant client)
# never requests, since it fetches the RFC-mandated root-level path. Mounting
# at the true root keeps the metadata (and /authorize, /token, /register,
# /auth/callback) at root while the JSON-RPC endpoint stays at /mcp.
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

app.include_router(router=McpConnectionsRouter, prefix="/user/mcp-connections", tags=["Developer"], include_in_schema=False)

app.include_router(router=HealthRouter, prefix="/health", tags=["Health"])

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
            "/search/": "Endpoint to find available sports bookings",
            "/venue/": "Endpoint to find Venues covered by Sportscanner monitoring",
            "/docs": "Documentation for API endpoints",
        },
    }

# Mounted last, at the app's true root, so every route defined above (and
# FastAPI's own /docs, /openapi.json, /redoc) is matched first by Starlette;
# this only catches what nothing else claimed — the MCP endpoint (/mcp) and
# FastMCP's OAuth routes (/authorize, /token, /register, /auth/callback,
# /.well-known/...). See the comment above `_mcp_app`'s construction for why
# it can't be nested under an extra "/mcp" prefix.
if _mcp_app is not None:
    app.mount("/", _mcp_app)
    logging.info("Sportscanner MCP server mounted (JSON-RPC endpoint at /mcp)")
