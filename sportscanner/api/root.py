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
import httpx


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

app.include_router(router=UsersRouter, prefix="/user", tags=["Authentication"])


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
