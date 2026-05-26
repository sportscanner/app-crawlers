"""
Tool registry

This module centralises tool imports from different files and exposes a
single `TOOL_FUNCTIONS` mapping which the FastMCP app can consume.

Add new tools by importing them below and adding them to the TOOL_FUNCTIONS
mapping.
"""

from typing import Dict, Callable
from sportscanner.mcp.tools.sportscanner_api import (
    acknowledge_notification,
    autocomplete_postcode,
    create_notification,
    find_venues_near_postcode,
    find_venues_near_location_query,
    get_api_root,
    get_postcode_metadata,
    get_scrapers_health,
    get_user_profile,
    get_venue_by_composite_key,
    list_notifications,
    list_venues,
    list_venues_by_sport,
    register_user,
    reverse_geocode_to_postcode,
    resolve_location_query,
    search_single_venue_availability,
    search_sport_availability,
    update_notification,
    update_user_profile,
    validate_postcode,
)

TOOL_FUNCTIONS: Dict[str, Callable] = {
    "sportscanner_api_root": get_api_root,
    "sportscanner_search_sport_availability": search_sport_availability,
    "sportscanner_search_single_venue_availability": (search_single_venue_availability),
    "sportscanner_list_venues": list_venues,
    "sportscanner_list_venues_by_sport": list_venues_by_sport,
    "sportscanner_find_venues_near_postcode": find_venues_near_postcode,
    "sportscanner_get_venue_by_composite_key": get_venue_by_composite_key,
    "sportscanner_validate_postcode": validate_postcode,
    "sportscanner_get_postcode_metadata": get_postcode_metadata,
    "sportscanner_autocomplete_postcode": autocomplete_postcode,
    "sportscanner_reverse_geocode_to_postcode": reverse_geocode_to_postcode,
    "sportscanner_resolve_location_query": resolve_location_query,
    "sportscanner_find_venues_near_location_query": find_venues_near_location_query,
    "sportscanner_get_scrapers_health": get_scrapers_health,
    "sportscanner_get_user_profile": get_user_profile,
    "sportscanner_register_user": register_user,
    "sportscanner_update_user_profile": update_user_profile,
    "sportscanner_list_notifications": list_notifications,
    "sportscanner_acknowledge_notification": acknowledge_notification,
    "sportscanner_create_notification": create_notification,
    "sportscanner_update_notification": update_notification,
}
