from hashlib import sha256

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sportscanner.api.routers.discovery.endpoints import create_router

ORIGIN = "https://api.example.test"


def client(mcp_enabled=True):
    app = FastAPI()
    app.include_router(create_router(ORIGIN, mcp_enabled))
    return TestClient(app)


def test_catalog_links_are_absolute_and_discover_the_real_contract():
    response = client().get("/.well-known/api-catalog")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/linkset+json"
    assert response.headers["access-control-allow-origin"] == "*"
    catalog, api = response.json()["linkset"]
    assert catalog["item"] == [{"href": ORIGIN}]
    assert api["anchor"] == ORIGIN
    assert api["service-desc"][0]["href"] == f"{ORIGIN}/openapi.json"
    assert api["status"][0]["href"] == f"{ORIGIN}/health/"
    guide = client().get("/agents.md")
    assert "POST /search/{sport}?date=YYYY-MM-DD" in guide.text
    assert ORIGIN in guide.text
    assert "https://api.sportscanner.co.uk" not in guide.text


def test_skill_digest_covers_exact_served_bytes_including_origin_substitution():
    http = client()
    index = http.get("/.well-known/agent-skills/index.json").json()
    assert index["$schema"].endswith("/0.2.0/schema.json")
    skill = index["skills"][0]
    artifact = http.get(skill["url"].removeprefix(ORIGIN))
    assert artifact.status_code == 200
    assert artifact.headers["content-type"].startswith("text/markdown")
    assert skill["digest"] == f"sha256:{sha256(artifact.content).hexdigest()}"
    assert artifact.text.startswith("---\nname: find-london-courts")


def test_ai_catalog_entries_have_one_locator_and_representative_queries():
    response = client().get("/.well-known/ai-catalog.json")
    assert response.headers["access-control-allow-origin"] == "*"
    data = response.json()
    assert data["host"]["identifier"] == "https://www.sportscanner.co.uk"
    for entry in data["entries"]:
        assert entry["identifier"].startswith("urn:air:sportscanner.co.uk:")
        assert ("url" in entry) != ("data" in entry)
        assert 2 <= len(entry["representativeQueries"]) <= 5


def test_server_card_uses_current_schema_and_correct_transport():
    http = client()
    card = http.get("/mcp/server-card").json()
    assert card == http.get("/.well-known/mcp/server-card.json").json()
    assert card["$schema"].endswith("/v1/server-card.schema.json")
    assert card["remotes"] == [{"type": "streamable-http", "url": f"{ORIGIN}/mcp"}]
    assert "capabilities" not in card  # Negotiated live, per the current extension.


def test_mcp_discovery_fails_closed_when_optional_server_is_unavailable():
    http = client(mcp_enabled=False)
    assert http.get("/mcp/server-card").status_code == 503
    assert http.get("/.well-known/oauth-protected-resource").status_code == 503
    assert len(http.get("/.well-known/ai-catalog.json").json()["entries"]) == 1
    assert http.get("/.well-known/api-catalog").status_code == 200


def test_resource_metadata_redirect_preserves_library_owned_oauth_contract():
    response = client().get(
        "/.well-known/oauth-protected-resource", follow_redirects=False
    )
    assert response.status_code == 307
    assert (
        response.headers["location"]
        == f"{ORIGIN}/.well-known/oauth-protected-resource/mcp"
    )
    auth = client().get("/auth.md")
    assert auth.status_code == 200
    assert "# SportScanner auth.md" in auth.text
    assert "does not implement autonomous agent account provisioning" in auth.text
