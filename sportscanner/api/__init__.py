from fastapi import FastAPI
from sportscanner.api.routers import venues, geolocation
from sportscanner.api.routers.search import badminton
from datetime import datetime

description = """
Discover, Compare, and Book Sports Facilities Across London

### Sportscanner API

You will be able to:

* **Search for sports bookings and drill down using advanced filters**
* **Find available playing venues which are covered under the search**
"""

app = FastAPI(
    title="Sportscanner",
    description=description,
    summary="API to fetch sports booking availability, analytics, and advanced filters",
    version="0.0.1",
    contact={
        "name": "Yasir khalid",
        "url": "https://www.linkedin.com/in/yasir-khalid",
        "email": "yasir_khalid@outlook.com",
    },
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
)

app.include_router(
    router= badminton.endpoints.router,
    prefix="/search/badminton",
    tags=["Search"]
)

app.include_router(
    router= venues.endpoints.router,
    prefix="/venues",
    tags=["Venues"]
)

app.include_router(
    router= geolocation.endpoints.router,
    prefix="/geolocation",
    tags=["Geolocation"]
)

@app.get("/", tags=["Root"])
async def root():
    """Root API landing page (should be deployed at api.domain.com)"""
    return {
        "timestamp": datetime.now(),
        "message": "Welcome to the Sportscanner API",
        "actions": {
            "/search/": "Endpoint to find available sports bookings",
            "/venue/": "Endpoint to find Venues covered by Sportscanner monitoring",
            "/docs": "Documentation for API endpoints",
        }
    }

