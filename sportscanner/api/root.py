import json
import os
from contextlib import asynccontextmanager
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
from sportscanner.api.routers.chat.endpoints import router as ChatRouter

from sportscanner.api.routers.users.endpoints import router as UsersRouter
from sportscanner.api.routers.venues.endpoints import router as VenuesRouter
from sportscanner.api.routers.health.endpoints import router as HealthRouter
from sportscanner.api.routers.notifications.endpoints import (
    router as NotificationsRouter,
)
from sportscanner.api.routers.business.endpoints import router as BusinessRouter
from sportscanner.mcp.server import mcp as sportscanner_mcp_server
from sportscanner.observability.phoenix import configure_phoenix_tracing
from sportscanner.storage.postgres.chat_repository import ensure_chat_tables
from sportscanner.storage.postgres.database import create_db_and_tables, engine

import httpx

mcp_http_app = sportscanner_mcp_server.http_app(path="/", transport="http")

description = """
## Sportscanner API

This aggregator API is a comprehensive platform designed to help sports enthusiasts find and book badminton, squash, and pickleball courts across London with ease.

You will be able to:

* Search for Badminton, Squash and Pickleball court bookings across London
* Find Venues near you that offers different types of sports, and amneties
* Compare prices, facilities, and peak/off-peak times. Book directly through venue links
"""


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    create_db_and_tables(engine)
    ensure_chat_tables(engine)
    configure_phoenix_tracing()
    async with mcp_http_app.lifespan(app):
        yield


app = FastAPI(
    title="Sportscanner",
    description=description,
    summary="Find Badminton, Squash, and Pickleball facilities; and available courts for hire across London",
    version="1.0.0",
    lifespan=app_lifespan,
    contact={
        "name": "Sportscanner (dev)",
        "url": "https://www.linkedin.com/company/sportscanner/",
        "email": "info@sportscanner.co.uk",
    },
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
)

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

app.include_router(
    router=GeolocationRouter, prefix="/geolocation", tags=["Geolocation"]
)

app.include_router(
    router=UsersRouter, prefix="/user", tags=["internal"], include_in_schema=False
)

app.include_router(router=HealthRouter, prefix="/health", tags=["Health"])

app.include_router(
    router=NotificationsRouter,
    prefix="/notifications",
    tags=["Notifications"],
)

app.include_router(
    router=ChatRouter,
    prefix="/chat",
    tags=["Agent"],
)

app.include_router(
    router=BusinessRouter,
    prefix="/business",
    tags=["Business"],
)

# Expose MCP over HTTP so external agent clients (including ADK MCP clients)
# can connect at /mcp.
app.mount(
    "/mcp",
    mcp_http_app,
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "sportscanner.api.root:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("ENV", "dev") != "prod",
    )
