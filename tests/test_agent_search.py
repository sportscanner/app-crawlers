import asyncio
from datetime import date, time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from sportscanner.api.routers.core.schemas import SportscannerSupportedSports
from sportscanner.api.routers.search import endpoints
from sportscanner.mcp.tools.search import find_available_courts


@pytest.mark.parametrize("sport", list(SportscannerSupportedSports))
def test_mcp_and_rest_share_court_filters_and_response(monkeypatch, sport):
    statements = []

    async def nearby(postcode, radius):
        assert postcode == "SE1 8UL"
        assert radius == 3
        return [
            SimpleNamespace(composite_key="court", distance=1.5),
            SimpleNamespace(composite_key="social", distance=2),
        ]

    def rows(engine, table, statement):
        if "sportsvenue" in str(statement):
            return ["social"]
        statements.append(statement)
        return []

    result = [
        {"date": "Sun, Oct 18", "distance": 1.5, "price": "£10", "availability": []}
    ]
    monkeypatch.setattr(endpoints, "get_venues_near_postcode", nearby)
    monkeypatch.setattr(endpoints.db, "get_all_rows", rows)
    monkeypatch.setattr(
        endpoints, "sort_and_format_grouped_slots_for_ui", lambda *_: result
    )
    app = FastAPI()
    app.include_router(endpoints.router, prefix="/search")
    response = TestClient(app).post(
        f"/search/{sport.value}?date=2026-10-18",
        json={
            "postcode": "SE1 8UL",
            "radius": 3,
            "sortBy": "distance",
            "indoor": True,
            "timeRange": {"starting": "18:00", "ending": "22:00"},
            "analytics": {"specifiedVenues": None},
        },
    )
    assert response.status_code == 200
    mcp_result = asyncio.run(
        find_available_courts(
            sport,
            "SE1 8UL",
            date(2026, 10, 18),
            starting_time=time(18),
            ending_time=time(22),
            indoor=True,
        )
    )
    assert mcp_result == response.json()
    for statement in statements:
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        assert "starts_at >" in sql  # Past slots must never return via MCP.
        assert "spaces > 0" in sql
        assert "'social'" not in sql  # Social sessions must not be sold as courts.
        assert "'court'" in sql
        assert "18:00:00" in sql and "22:00:00" in sql
        if sport.value in {"padel", "tennis", "pickleball"}:
            assert "indoor = true" in sql


def test_mcp_rejects_inverted_time_window_before_querying():
    with pytest.raises(ValueError, match="before ending_time"):
        asyncio.run(
            find_available_courts(
                SportscannerSupportedSports.TENNIS,
                "SE1 8UL",
                date(2026, 10, 18),
                starting_time=time(22),
                ending_time=time(18),
            )
        )


def test_rest_keeps_invalid_sport_and_date_validation():
    app = FastAPI()
    app.include_router(endpoints.router, prefix="/search")
    http = TestClient(app)
    assert http.post("/search/football?date=2026-10-18", json={}).status_code == 422
    assert http.post("/search/tennis?date=invalid", json={}).status_code == 422
    schema = app.openapi()
    assert (
        schema["paths"]["/search/{sport}"]["post"]["operationId"]
        == "search_search__sport__post"
    )
    assert (
        schema["components"]["schemas"]["SearchCriteria"]["examples"][0]["postcode"]
        == "SE1 8UL"
    )
