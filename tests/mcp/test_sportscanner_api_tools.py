import asyncio
from datetime import date, time
from typing import Any

import pytest

from sportscanner.mcp.tools import sportscanner_api as api_tools


def run(coro):
    return asyncio.run(coro)


SEARCH_FILTERS = api_tools.SearchFilters(
    postcode="SE17TP",
    radius=8.0,
    timeRange=api_tools.SearchTimeRange(starting=time(18, 0), ending=time(22, 0)),
    analytics=api_tools.SearchAnalyticsFilters(
        specifiedVenues=["c3a8df88"],
        searchUserPreferredLocations=True,
    ),
    sortBy="distance",
)

USER_UPDATE_PAYLOAD = api_tools.UserProfileUpdatePayload(
    onboarding=True,
    preferences={"postcode": "SE17TP", "searchRadius": 8},
)

CREATE_NOTIFICATION_PAYLOAD = api_tools.CreateNotificationPayload(
    title="Maintenance",
    message="API maintenance at 11 PM",
    active=True,
)

UPDATE_NOTIFICATION_PAYLOAD = api_tools.UpdateNotificationPayload(
    title="Updated Maintenance Notice"
)


@pytest.mark.parametrize(
    "tool_name,args,kwargs,fake_response,expected",
    [
        (
            "get_api_root",
            (),
            {},
            {"message": "ok"},
            {
                "method": "GET",
                "path": "/",
                "params": None,
                "json_body": None,
                "authorization": None,
            },
        ),
        (
            "search_sport_availability",
            ("badminton", date(2026, 5, 23), SEARCH_FILTERS),
            {},
            [{"venue": "A"}],
            {
                "method": "POST",
                "path": "/search/badminton",
                "params": {"date": "2026-05-23"},
                "json_body": SEARCH_FILTERS.model_dump(mode="json", exclude_none=True),
                "authorization": None,
            },
        ),
        (
            "search_single_venue_availability",
            ("squash", "abc12345", date(2026, 5, 24)),
            {},
            [{"slot": "19:00"}],
            {
                "method": "POST",
                "path": "/search/squash/abc12345",
                "params": {"date": "2026-05-24"},
                "json_body": None,
                "authorization": None,
            },
        ),
        (
            "list_venues",
            (),
            {"limit": 25},
            [{"composite_key": "a"}],
            {
                "method": "GET",
                "path": "/venues/",
                "params": {"limit": 25},
                "json_body": None,
                "authorization": None,
            },
        ),
        (
            "list_venues_by_sport",
            ("pickleball",),
            {"limit": 12},
            [{"composite_key": "b"}],
            {
                "method": "GET",
                "path": "/venues/sports/pickleball",
                "params": {"limit": 12},
                "json_body": None,
                "authorization": None,
            },
        ),
        (
            "find_venues_near_postcode",
            ("SE17TP",),
            {"distance_miles": 6.5},
            [{"composite_key": "c"}],
            {
                "method": "GET",
                "path": "/venues/near",
                "params": {"postcode": "SE17TP", "distance": 6.5},
                "json_body": None,
                "authorization": None,
            },
        ),
        (
            "get_venue_by_composite_key",
            ("c3a8df88",),
            {},
            [{"venue_name": "Finsbury Leisure Centre"}],
            {
                "method": "GET",
                "path": "/venues/c3a8df88",
                "params": None,
                "json_body": None,
                "authorization": None,
            },
        ),
        (
            "validate_postcode",
            ("SE17TP",),
            {},
            {"valid": True},
            {
                "method": "GET",
                "path": "/geolocation/validate-postcode",
                "params": {"postcode": "SE17TP"},
                "json_body": None,
                "authorization": None,
            },
        ),
        (
            "get_postcode_metadata",
            ("SE17TP",),
            {},
            {"valid": True, "metadata": {"postcode": "SE17TP"}},
            {
                "method": "GET",
                "path": "/geolocation/metadata-postcode",
                "params": {"postcode": "SE17TP"},
                "json_body": None,
                "authorization": None,
            },
        ),
        (
            "autocomplete_postcode",
            ("SE1",),
            {},
            ["SE1 7TP"],
            {
                "method": "GET",
                "path": "/geolocation/autocomplete",
                "params": {"q": "SE1"},
                "json_body": None,
                "authorization": None,
            },
        ),
        (
            "reverse_geocode_to_postcode",
            (51.5023, -0.0383),
            {},
            {"postcode": "E14 0SX"},
            {
                "method": "GET",
                "path": "/geolocation/reverse",
                "params": {"lat": 51.5023, "lon": -0.0383},
                "json_body": None,
                "authorization": None,
            },
        ),
        (
            "resolve_location_query",
            ("Paddington",),
            {},
            {"resolved_postcode": "W2 1AA", "source": "place_search"},
            {
                "method": "GET",
                "path": "/geolocation/resolve-location",
                "params": {"q": "Paddington"},
                "json_body": None,
                "authorization": None,
            },
        ),
        (
            "find_venues_near_location_query",
            ("E14",),
            {"distance_miles": 4.0},
            {
                "query": "E14",
                "normalized_query": "E14",
                "resolved": True,
                "resolved_location": {
                    "resolved_postcode": "E14 0AA",
                    "source": "postcode_autocomplete",
                },
                "distance_miles": 4.0,
                "venues": [{"composite_key": "v-1"}],
            },
            None,
        ),
        (
            "get_scrapers_health",
            ("badminton",),
            {},
            [{"venue_name": "Venue A", "health": "ok"}],
            {
                "method": "GET",
                "path": "/health/scrapers",
                "params": {"sports": "badminton"},
                "json_body": None,
                "authorization": None,
            },
        ),
        (
            "get_user_profile",
            ("refresh-token",),
            {},
            {"id": "user_123"},
            {
                "method": "GET",
                "path": "/user/",
                "params": None,
                "json_body": None,
                "authorization": "refresh-token",
            },
        ),
        (
            "register_user",
            ("refresh-token",),
            {},
            {"success": True},
            {
                "method": "POST",
                "path": "/user/",
                "params": None,
                "json_body": None,
                "authorization": "refresh-token",
            },
        ),
        (
            "update_user_profile",
            ("refresh-token", USER_UPDATE_PAYLOAD),
            {},
            {"success": True},
            {
                "method": "PATCH",
                "path": "/user/",
                "params": None,
                "json_body": USER_UPDATE_PAYLOAD.model_dump(
                    mode="json", exclude_none=True
                ),
                "authorization": "refresh-token",
            },
        ),
        (
            "list_notifications",
            ("refresh-token",),
            {},
            [{"id": "notif-1"}],
            {
                "method": "GET",
                "path": "/notifications/",
                "params": None,
                "json_body": None,
                "authorization": "refresh-token",
            },
        ),
        (
            "create_notification",
            ("refresh-token", CREATE_NOTIFICATION_PAYLOAD),
            {},
            {"id": "notif-2", "active": True},
            {
                "method": "POST",
                "path": "/notifications/admin",
                "params": None,
                "json_body": CREATE_NOTIFICATION_PAYLOAD.model_dump(mode="json"),
                "authorization": "refresh-token",
            },
        ),
        (
            "update_notification",
            ("notif-2", "refresh-token", UPDATE_NOTIFICATION_PAYLOAD),
            {},
            {"id": "notif-2", "title": "Updated Maintenance Notice"},
            {
                "method": "PATCH",
                "path": "/notifications/admin/notif-2",
                "params": None,
                "json_body": UPDATE_NOTIFICATION_PAYLOAD.model_dump(
                    mode="json", exclude_none=True
                ),
                "authorization": "refresh-token",
            },
        ),
    ],
)
def test_tools_send_expected_request(
    monkeypatch,
    tool_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    fake_response: Any,
    expected: dict[str, Any],
):
    captured: dict[str, Any] = {}

    async def fake_request(method: str, path: str, **request_kwargs: Any):
        captured["method"] = method
        captured["path"] = path
        captured.update(request_kwargs)
        return fake_response

    monkeypatch.setattr(api_tools, "_sportscanner_api_request", fake_request)

    if tool_name == "find_venues_near_location_query":
        async def fake_resolve_location_query(query: str):
            assert query == "E14"
            return {
                "resolved_postcode": "E14 0AA",
                "source": "postcode_autocomplete",
            }

        async def fake_find_venues_near_postcode(
            postcode: str,
            distance_miles: float = 10.0,
        ):
            assert postcode == "E14 0AA"
            assert distance_miles == 4.0
            return [{"composite_key": "v-1"}]

        monkeypatch.setattr(
            api_tools,
            "resolve_location_query",
            fake_resolve_location_query,
        )
        monkeypatch.setattr(
            api_tools,
            "find_venues_near_postcode",
            fake_find_venues_near_postcode,
        )
        result = run(getattr(api_tools, tool_name)(*args, **kwargs))
        assert result == fake_response
        return

    result = run(getattr(api_tools, tool_name)(*args, **kwargs))
    assert result == fake_response
    assert expected is not None
    assert captured["method"] == expected["method"]
    assert captured["path"] == expected["path"]
    assert captured.get("params") == expected["params"]
    assert captured.get("json_body") == expected["json_body"]
    assert captured.get("authorization") == expected["authorization"]


def test_acknowledge_notification_returns_normalized_result(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_request(method: str, path: str, **request_kwargs: Any):
        captured["method"] = method
        captured["path"] = path
        captured.update(request_kwargs)
        return {"success": True, "status_code": 204}

    monkeypatch.setattr(api_tools, "_sportscanner_api_request", fake_request)

    response = run(
        api_tools.acknowledge_notification(
            notification_id="notif-1",
            authorization="refresh-token",
        )
    )

    assert response == {
        "notification_id": "notif-1",
        "acknowledged": True,
        "status_code": 204,
    }
    assert captured["method"] == "POST"
    assert captured["path"] == "/notifications/notif-1/acknowledge"
    assert captured["authorization"] == "refresh-token"


def test_sportscanner_api_request_success(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = "ok"
        content = b'{"ok":true}'

        @staticmethod
        def json():
            return {"ok": True}

    class FakeAsyncClient:
        captured: dict[str, Any] = {}

        def __init__(self, timeout: float):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, method: str, url: str, **kwargs: Any):
            self.__class__.captured = {
                "method": method,
                "url": url,
                **kwargs,
            }
            return FakeResponse()

    monkeypatch.setattr(api_tools, "_get_api_base_url", lambda: "http://localhost:8000")
    monkeypatch.setattr(api_tools.httpx, "AsyncClient", FakeAsyncClient)

    response = run(
        api_tools._sportscanner_api_request(
            "GET",
            "/venues/",
            params={"limit": 5},
            authorization="refresh-token",
        )
    )

    assert response == {"ok": True}
    assert FakeAsyncClient.captured["method"] == "GET"
    assert FakeAsyncClient.captured["url"] == "http://localhost:8000/venues/"
    assert FakeAsyncClient.captured["params"] == {"limit": 5}
    assert FakeAsyncClient.captured["headers"]["Authorization"] == "refresh-token"


def test_find_venues_near_location_query_returns_unresolved_payload_without_raising(
    monkeypatch,
):
    async def fake_resolve_location_query(query: str):
        return {
            "query": query,
            "source": "unresolved",
            "message": "Could not resolve that location.",
        }

    async def fake_find_venues_near_postcode(postcode: str, distance_miles: float = 10.0):
        raise AssertionError("Should not search venues when postcode cannot be resolved.")

    monkeypatch.setattr(
        api_tools,
        "resolve_location_query",
        fake_resolve_location_query,
    )
    monkeypatch.setattr(
        api_tools,
        "find_venues_near_postcode",
        fake_find_venues_near_postcode,
    )
    monkeypatch.setattr(
        api_tools,
        "_resolve_postcode_via_nominatim",
        lambda query: asyncio.sleep(0, result=None),
    )

    response = run(
        api_tools.find_venues_near_location_query(
            location_query="near ???",
            distance_miles=5.0,
        )
    )

    assert response["resolved"] is False
    assert response["venues"] == []
    assert response["distance_miles"] == 5.0
    assert response["message"] == "Could not resolve that location."


def test_find_venues_near_location_query_retries_with_normalized_query(monkeypatch):
    calls: list[str] = []

    async def fake_resolve_location_query(query: str):
        calls.append(query)
        if query == "within 4 miles of E14?":
            return {"query": query, "source": "unresolved", "message": "unresolved"}
        if query == "E14":
            return {
                "query": query,
                "resolved_postcode": "E14 0AA",
                "source": "postcode_autocomplete",
            }
        return {"query": query, "source": "unresolved", "message": "unresolved"}

    async def fake_find_venues_near_postcode(postcode: str, distance_miles: float = 10.0):
        assert postcode == "E14 0AA"
        assert distance_miles == 4.0
        return [{"composite_key": "venue-123"}]

    monkeypatch.setattr(
        api_tools,
        "resolve_location_query",
        fake_resolve_location_query,
    )
    monkeypatch.setattr(
        api_tools,
        "find_venues_near_postcode",
        fake_find_venues_near_postcode,
    )
    monkeypatch.setattr(
        api_tools,
        "_resolve_postcode_via_nominatim",
        lambda query: asyncio.sleep(0, result=None),
    )

    response = run(
        api_tools.find_venues_near_location_query(
            location_query="within 4 miles of E14?",
            distance_miles=4.0,
        )
    )

    assert calls == ["within 4 miles of E14?", "E14"]
    assert response["resolved"] is True
    assert response["normalized_query"] == "E14"
    assert response["resolved_location"]["resolved_postcode"] == "E14 0AA"
    assert len(response["venues"]) == 1


def test_sportscanner_api_request_handles_204(monkeypatch):
    class FakeResponse:
        status_code = 204
        text = ""
        content = b""

        @staticmethod
        def json():
            raise ValueError("No JSON")

    class FakeAsyncClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, method: str, url: str, **kwargs: Any):
            return FakeResponse()

    monkeypatch.setattr(api_tools, "_get_api_base_url", lambda: "http://localhost:8000")
    monkeypatch.setattr(api_tools.httpx, "AsyncClient", FakeAsyncClient)

    response = run(
        api_tools._sportscanner_api_request(
            "POST",
            "/notifications/abc/acknowledge",
            authorization="refresh-token",
        )
    )
    assert response == {"success": True, "status_code": 204}


def test_sportscanner_api_request_error_contains_context(monkeypatch):
    class FakeResponse:
        status_code = 400
        text = "Bad request"
        content = b'{"detail":"postcode is invalid"}'

        @staticmethod
        def json():
            return {"detail": "postcode is invalid"}

    class FakeAsyncClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, method: str, url: str, **kwargs: Any):
            return FakeResponse()

    monkeypatch.setattr(api_tools, "_get_api_base_url", lambda: "http://localhost:8000")
    monkeypatch.setattr(api_tools.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(ValueError, match="400"):
        run(
            api_tools._sportscanner_api_request(
                "GET",
                "/venues/near",
                params={"postcode": "INVALID"},
            )
        )


def test_search_time_range_validation_rejects_invalid_window():
    with pytest.raises(ValueError, match="starting"):
        api_tools.SearchTimeRange(starting=time(20, 0), ending=time(19, 0))


def test_user_profile_update_payload_requires_content():
    with pytest.raises(ValueError, match="At least one"):
        api_tools.UserProfileUpdatePayload()


def test_update_notification_payload_requires_content():
    with pytest.raises(ValueError, match="At least one"):
        api_tools.UpdateNotificationPayload()
