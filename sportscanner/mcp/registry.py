"""
Tool registry

This module centralises tool imports from different files and exposes a
single `TOOL_FUNCTIONS` mapping which the FastMCP app can consume.

Add new tools by importing them below and adding them to the TOOL_FUNCTIONS
mapping.
"""
from typing import Dict, Callable
from sportscanner.mcp.tools.geolocation import forward_geocoding, postcode_search
from sportscanner.mcp.tools.search import find_available_courts
from sportscanner.api.routers.venues.utils import get_venues_from_database, get_venue_by_composite_key, get_sports_venues_within_radius


TOOL_FUNCTIONS: Dict[str, Callable] = {
    "find_available_courts": find_available_courts,
    "Forward Geocoding": forward_geocoding,
    # "Postcode Search": postcode_search,
    "Get Venues": get_venues_from_database,
    "Get Venue By Composite Key": get_venue_by_composite_key,
    "Get Sports Venues Within Radius": get_sports_venues_within_radius,
}