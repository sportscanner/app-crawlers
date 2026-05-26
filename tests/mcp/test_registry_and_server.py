import asyncio

from fastapi.testclient import TestClient

from sportscanner.api.root import app as api_app
from sportscanner.mcp.registry import TOOL_FUNCTIONS
from sportscanner.mcp.server import mcp

EXPECTED_TOOL_NAMES = {
    "sportscanner_api_root",
    "sportscanner_search_sport_availability",
    "sportscanner_search_single_venue_availability",
    "sportscanner_list_venues",
    "sportscanner_list_venues_by_sport",
    "sportscanner_find_venues_near_postcode",
    "sportscanner_get_venue_by_composite_key",
    "sportscanner_validate_postcode",
    "sportscanner_get_postcode_metadata",
    "sportscanner_autocomplete_postcode",
    "sportscanner_reverse_geocode_to_postcode",
    "sportscanner_resolve_location_query",
    "sportscanner_find_venues_near_location_query",
    "sportscanner_get_scrapers_health",
    "sportscanner_get_user_profile",
    "sportscanner_register_user",
    "sportscanner_update_user_profile",
    "sportscanner_list_notifications",
    "sportscanner_acknowledge_notification",
    "sportscanner_create_notification",
    "sportscanner_update_notification",
}


def test_tool_registry_is_complete():
    assert set(TOOL_FUNCTIONS.keys()) == EXPECTED_TOOL_NAMES
    assert all(callable(fn) for fn in TOOL_FUNCTIONS.values())


def test_server_registers_all_tools():
    tools = asyncio.run(mcp.list_tools(run_middleware=False))
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name.keys()) == EXPECTED_TOOL_NAMES


def test_tool_schemas_and_descriptions_are_documented():
    tools = asyncio.run(mcp.list_tools(run_middleware=False))

    for tool in tools:
        assert tool.description is not None
        assert tool.description.strip() != ""

        parameters = tool.parameters
        assert parameters.get("type") == "object"

        for param_schema in parameters.get("properties", {}).values():
            assert "description" in param_schema or "$ref" in param_schema

    search_tool = next(
        tool for tool in tools if tool.name == "sportscanner_search_sport_availability"
    )
    search_schema = search_tool.parameters

    assert search_schema["properties"]["sport"]["description"]
    assert search_schema["properties"]["search_date"]["description"]
    assert search_schema["properties"]["filters"]["description"]
    assert search_schema["$defs"]["SearchFilters"]["properties"]["postcode"][
        "description"
    ]


def test_mcp_mount_works_with_parent_fastapi_lifespan():
    """
    Regression test for FastMCP task-group initialization.

    When MCP app lifespan is not composed with parent FastAPI lifespan,
    POST /mcp/ returns 500 with "Task group is not initialized".
    """
    with TestClient(api_app) as client:
        response = client.post(
            "/mcp/",
            headers={"Accept": "application/json, text/event-stream"},
            json={},
        )

    assert response.status_code != 500
