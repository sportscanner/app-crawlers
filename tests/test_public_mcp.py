"""Exercise the actual mounted transport and the separate account boundary."""

import json

import pytest
from fastapi.testclient import TestClient

from sportscanner.api.root import app
from sportscanner.mcp.tools import search as search_tools
from sportscanner.mcp.registry import TOOL_FUNCTIONS
from sportscanner.mcp.server import mcp

HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture(scope="module")
def client():
    # One transport lifespan/loop, matching production. SSE's global shutdown
    # event is not safe to reuse across TestClient instances on separate loops.
    with TestClient(app) as http:
        yield http


def rpc(client, method, params=None, headers=None):
    response = client.post(
        "/mcp",
        headers={**HEADERS, **(headers or {})},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    assert "www-authenticate" not in response.headers
    if response.headers["content-type"].startswith("text/event-stream"):
        return json.loads(
            next(
                line[6:]
                for line in response.text.splitlines()
                if line.startswith("data: ")
            )
        )
    return response.json()


def test_anonymous_transport_initializes_and_lists_only_public_tools(client):
    assert mcp.auth is None
    result = rpc(
        client,
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "anonymous-regression", "version": "1.0"},
        },
    )["result"]
    assert result["serverInfo"]["name"] == "Sportscanner Unified MCP"
    tools = rpc(client, "tools/list")["result"]["tools"]
    assert {t["name"] for t in tools} == {f.__name__ for f in TOOL_FUNCTIONS.values()}
    assert len(tools) == 5
    # Old clients with an obsolete token can still use public data.
    assert "result" in rpc(
        client, "tools/list", headers={"Authorization": "Bearer obsolete"}
    )
    for path in (
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-authorization-server",
        "/authorize",
    ):
        assert client.get(path).status_code == 404
    for path in ("/register", "/token"):
        assert client.post(path, json={}).status_code == 404


def test_anonymous_mcp_search_calls_the_existing_public_rest_handler(
    monkeypatch, client
):
    calls = []

    async def search(sport, date, filters):
        calls.append((sport.value, date.isoformat(), filters.postcode))
        return [
            {"venue": "Public court", "availability": [], "healthcheck": "deprecated"}
        ]

    monkeypatch.setattr(search_tools, "search_courts", search)
    result = rpc(
        client,
        "tools/call",
        {
            "name": "find_available_courts",
            "arguments": {
                "sport": "badminton",
                "postcode": "SE1 8UL",
                "date": "2026-10-18",
            },
        },
    )["result"]
    assert not result.get("isError", False), result
    assert "Public court" in str(result)
    assert calls == [("badminton", "2026-10-18", "SE1 8UL")]


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/user/", None),
        ("POST", "/user/", None),
        ("PATCH", "/user/", {"preferences": {"postcode": "SE1 8UL"}}),
        ("GET", "/user/tokens/", None),
        ("POST", "/user/tokens/", {"name": "test"}),
        ("GET", "/user/mcp-connections/", None),
    ],
)
def test_private_account_routes_still_reject_missing_credentials(
    client, method, path, body
):
    # Existing Kinde contract rejects missing refresh tokens with 400.
    response = client.request(method, path, json=body)
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "invalid_request"
