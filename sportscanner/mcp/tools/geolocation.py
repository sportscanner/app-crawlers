"""
Geoapify MCP Server Handlers

This module implements all the tool functions for the Geoapify MCP server.
Each function corresponds to a tool defined in tools.json and implements
the actual API calls to Geoapify services.
"""

import os
import httpx
from typing import Dict, Any, Optional, Union, List, Annotated
from typing import Annotated, Literal, Optional
from pydantic import Field
from dotenv import load_dotenv
from sportscanner.mcp.tools.schemas import PostcodeSearch, ForwardGeocoding
# Load environment variables
load_dotenv()
GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_KEY", "641bb8358e4741119e51746ae3476049")
# Base URL for Geoapify API
GEOAPIFY_BASE_URL = "https://api.geoapify.com"


async def geoapify_request(
    endpoint: str,
    params: Dict[str, Any],
    method: str = "GET",
    json_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generic function to make requests to Geoapify API.

    Args:
        endpoint: API endpoint (e.g., "/v1/geocode/search")
        params: Query parameters
        method: HTTP method (GET or POST)
        json_body: JSON body for POST requests

    Returns:
        API response as dictionary

    Raises:
        ValueError: If API key is not set or API returns an error
    """
    if not GEOAPIFY_API_KEY:
        raise ValueError("GEOAPIFY_KEY environment variable not set")

    # Add API key to parameters
    params = params.copy()
    params["apiKey"] = GEOAPIFY_API_KEY

    url = f"{GEOAPIFY_BASE_URL}{endpoint}"

    async with httpx.AsyncClient() as client:
        try:
            if method.upper() == "POST":
                response = await client.post(url, params=params, json=json_body)
            else:
                response = await client.get(url, params=params)

            # Check for HTTP errors
            if response.status_code != 200:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message", response.text)
                except Exception:
                    error_msg = response.text
                raise ValueError(
                    f"Geoapify API error ({response.status_code}): {error_msg}"
                )

            return response.json()

        except httpx.RequestError as e:
            raise ValueError(f"Request error: {e}")
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"Unexpected error: {e}")


async def forward_geocoding(
    text: Annotated[str, Field(description="Free-text address or postcode or place name, e.g. 'Eiffel Tower Paris'")],
    language: Annotated[str, Field(description="Preferred response language code, e.g. 'en'")]="en",
    filter: Annotated[str, Field(description="Optional filter DSL (e.g., 'countrycode:gb' or 'rect:minLon,minLat,maxLon,maxLat')")] = "countrycode:gb",
    bias: Annotated[str, Field(description="Optional bias DSL (e.g., 'point:lon,lat')")] = None,
) -> ForwardGeocoding:
    """
    This tool does forward geocoding to convert an address or postcode or place name into geographic coordinates.
    """
    # Build parameters with hard limit of 20
    params = {"text": text, "limit": 20, "format": "json"}

    # Add optional parameters
    if language is not None:
        params["lang"] = language
    if filter is not None:
        params["filter"] = filter
    if bias is not None:
        params["bias"] = bias

    # Make the API request and map Geoapify errors to ToolError so callers get
    # consistent, user-friendly messages when the tool is invoked incorrectly
    response = await geoapify_request("/v1/geocode/search", params)

    # Transform the response to match the simplified schema
    if "features" in response:
        # Handle GeoJSON format response
        results = []
        for feature in response["features"]:
            props = feature.get("properties", {})
            geometry = feature.get("geometry", {})
            coordinates = geometry.get("coordinates", [])

            result = {
                "formatted": props.get("formatted", ""),
                "lat": coordinates[1] if len(coordinates) >= 2 else None,
                "lon": coordinates[0] if len(coordinates) >= 2 else None,
            }

            # Add optional fields if they exist
            for field in [
                "country",
                "state",
                "county",
                "city",
                "postcode",
                "street",
                "housenumber",
            ]:
                if field in props:
                    result[field] = props[field]

            results.append(result)

        return {"results": results}

    elif "results" in response:
        # Handle JSON format response - already in the right format
        simplified_results = []
        for result in response["results"]:
            simplified_result = {
                "formatted": result.get("formatted", ""),
                "lat": result.get("lat"),
                "lon": result.get("lon"),
            }

            # Add optional fields if they exist
            for field in [
                "country",
                "state",
                "county",
                "city",
                "postcode",
                "street",
                "housenumber",
            ]:
                if field in result:
                    simplified_result[field] = result[field]

            simplified_results.append(simplified_result)

        output = {"results": simplified_results}
        return ForwardGeocoding(**output)


async def postcode_search(
    postcode: Annotated[str, Field(description="Postcode to search for")] = None,
    lat: Annotated[float, Field(description="Latitude")] = None,
    lon: Annotated[float, Field(description="Longitude")] = None,
    country_code: Annotated[
        str,
        Field(
            description="ISO 3166-1 alpha-2 country code, 2 lowercase letters (e.g. 'gb', 'us'). Required by Geoapify API.",
            min_length=2,
            max_length=2,
            pattern="^[a-z]{2}$"
        )
    ] = "gb",
    geometry_mode: Annotated[Literal["point", "polygon"], Field(description="Return centroid points or original postcode polygons when available")] = "point",
    language: Annotated[str, Field(description="Language code, e.g. 'en', 'de', 'fr'")] = "en",
    page: Annotated[int, Field(description="1-based page index; each page returns up to 20 results", ge=1)] = 1,
) -> PostcodeSearch:
    """
    This tool performs a postcode search using Geoapify's Postcode Search API.
    It can search by postcode or by geographic coordinates (latitude and longitude).
    """
    if not postcode and not (lat is not None and lon is not None):
        raise ValueError(
            "Either 'postcode' or both 'lat' and 'lon' parameters are required"
        )

    # Calculate pagination offset
    offset = (page - 1) * 20

    params = {
        "format": "geojson",
        "limit": 20,
        "offset": offset,
    }

    # Add location parameters
    if postcode is not None:
        params["postcode"] = postcode
    if lat is not None:
        params["lat"] = lat
    if lon is not None:
        params["lon"] = lon

    # Add optional parameters with API parameter mapping
    if country_code is not None:
        params["countrycode"] = country_code
    if geometry_mode == "polygon":
        params["geometry"] = "original"
    else:
        params["geometry"] = "point"
    if language is not None:
        params["lang"] = language

    response = await geoapify_request("/v1/postcode/search", params)

    # Ensure we always return a FeatureCollection with proper properties
    if response.get("type") == "FeatureCollection":
        # Already a FeatureCollection - fix any malformed features
        for feature in response.get("features", []):
            # Fix nested geometry structure if it exists (Geoapify bug workaround)
            if feature.get("geometry") and isinstance(feature["geometry"], dict):
                geom = feature["geometry"]
                # Check if geometry is actually a nested Feature
                if geom.get("type") == "Feature" and "geometry" in geom:
                    # Extract the actual geometry from the nested structure
                    feature["geometry"] = geom["geometry"]

            if not feature.get("properties"):
                feature["properties"] = {}
            props = feature["properties"]

            # Ensure postcode and country_code are always present
            if "postcode" not in props:
                props["postcode"] = postcode or ""
            if "country_code" not in props:
                props["country_code"] = country_code or ""

    elif response.get("type") == "Feature":
        # Single feature - wrap in FeatureCollection
        feature = response

        # Fix nested geometry structure if it exists (Geoapify bug workaround)
        if feature.get("geometry") and isinstance(feature["geometry"], dict):
            geom = feature["geometry"]
            # Check if geometry is actually a nested Feature
            if geom.get("type") == "Feature" and "geometry" in geom:
                # Extract the actual geometry from the nested structure
                feature["geometry"] = geom["geometry"]

        if not feature.get("properties"):
            feature["properties"] = {}
        props = feature["properties"]

        # Ensure postcode and country_code are always present
        if "postcode" not in props:
            props["postcode"] = postcode or ""
        if "country_code" not in props:
            props["country_code"] = country_code or ""

        response = {"type": "FeatureCollection", "features": [feature]}
    else:
        # Handle other response formats (shouldn't happen with format=geojson)
        # Create a minimal valid FeatureCollection
        response = {"type": "FeatureCollection", "features": []}

    return PostcodeSearch(**response)


import asyncio

if __name__ == "__main__":
    result = asyncio.run(forward_geocoding(text="Eiffel Tower Paris"))
    print(result)