"""Discovery documents describe existing services without changing their auth."""

from hashlib import sha256
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, Response

VERSION = "1.0.0"
RESOURCES = Path(__file__).parent
PUBLIC_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "public, max-age=300",
}


def discovery_links(origin: str) -> str:
    return ", ".join(
        [
            f'<{origin}/.well-known/api-catalog>; rel="api-catalog"',
            f'<{origin}/openapi.json>; rel="service-desc"; type="application/json"',
            f'<{origin}/agents.md>; rel="service-doc"; type="text/markdown"',
        ]
    )


def create_router(origin: str, mcp_enabled: bool) -> APIRouter:
    origin = origin.rstrip("/")
    router = APIRouter(include_in_schema=False)

    def markdown(filename: str) -> Response:
        # Digests cover the exact bytes served after public-origin substitution.
        body = (
            (RESOURCES / filename)
            .read_text()
            .replace("https://api.sportscanner.co.uk", origin)
        )
        return Response(body, media_type="text/markdown", headers=PUBLIC_HEADERS)

    @router.get("/agents.md")
    @router.get("/llms-full.txt")
    async def agent_guide():
        return markdown("agents.md")

    @router.get("/auth.md")
    async def auth_guide():
        return markdown("auth.md")

    @router.get("/.well-known/api-catalog")
    async def api_catalog():
        return JSONResponse(
            {
                "linkset": [
                    {
                        "anchor": f"{origin}/.well-known/api-catalog",
                        "item": [{"href": origin}],
                    },
                    {
                        "anchor": origin,
                        "service-desc": [
                            {
                                "href": f"{origin}/openapi.json",
                                "type": "application/json",
                            }
                        ],
                        "service-doc": [
                            {"href": f"{origin}/agents.md", "type": "text/markdown"}
                        ],
                        "status": [
                            {"href": f"{origin}/health/", "type": "application/json"}
                        ],
                    },
                ]
            },
            media_type="application/linkset+json",
            headers=PUBLIC_HEADERS,
        )

    @router.get("/.well-known/agent-skills/index.json")
    async def skills_index():
        artifact = markdown("SKILL.md").body
        return JSONResponse(
            {
                "$schema": "https://schemas.agentskills.io/discovery/0.2.0/schema.json",
                "skills": [
                    {
                        "name": "find-london-courts",
                        "type": "skill-md",
                        "description": "Find London court availability, prices and booking links using SportScanner's public API.",
                        "url": f"{origin}/.well-known/agent-skills/find-london-courts/SKILL.md",
                        "digest": f"sha256:{sha256(artifact).hexdigest()}",
                    }
                ],
            },
            headers=PUBLIC_HEADERS,
        )

    @router.get("/.well-known/agent-skills/find-london-courts/SKILL.md")
    async def court_skill():
        return markdown("SKILL.md")

    @router.get("/mcp/server-card")
    @router.get("/.well-known/mcp/server-card.json")
    async def mcp_card():
        if not mcp_enabled:
            raise HTTPException(503, "MCP is unavailable on this deployment")
        # Current SEP-2127 extension schema. Tools/capabilities are negotiated
        # over MCP, rather than frozen into a static server card.
        return JSONResponse(
            {
                "$schema": "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json",
                "name": "uk.co.sportscanner/courts",
                "title": "Sportscanner Unified MCP",
                "version": VERSION,
                "description": "Find London sports courts, availability, prices and provider booking links.",
                "websiteUrl": f"{origin}/agents.md",
                "remotes": [{"type": "streamable-http", "url": f"{origin}/mcp"}],
            },
            headers=PUBLIC_HEADERS,
        )

    @router.get("/.well-known/oauth-protected-resource")
    async def resource_metadata():
        if not mcp_enabled:
            raise HTTPException(503, "MCP is unavailable on this deployment")
        # FastMCP owns OAuth metadata. Never invent a second issuer.
        return RedirectResponse(
            f"{origin}/.well-known/oauth-protected-resource/mcp", status_code=307
        )

    @router.get("/.well-known/ai-catalog.json")
    async def ai_catalog():
        entries = [
            {
                "identifier": "urn:air:sportscanner.co.uk:api:courts",
                "displayName": "SportScanner public court availability API",
                "type": "application/json",
                "url": f"{origin}/openapi.json",
                "representativeQueries": [
                    "Find badminton courts near SE1 8UL tomorrow evening",
                    "Compare indoor padel court prices in London",
                    "Find tennis, squash or pickleball availability near my postcode",
                ],
            }
        ]
        if mcp_enabled:
            entries.append(
                {
                    "identifier": "urn:air:sportscanner.co.uk:mcp:courts",
                    "displayName": "SportScanner court search MCP server",
                    "type": "application/mcp-server-card+json",
                    "url": f"{origin}/mcp/server-card",
                    "representativeQueries": [
                        "Use SportScanner to find a court on my behalf",
                        "Find available squash courts with booking links",
                    ],
                }
            )
        return JSONResponse(
            {
                "specVersion": "1.0",
                "host": {
                    "displayName": "SportScanner",
                    "identifier": "https://www.sportscanner.co.uk",
                },
                "entries": entries,
            },
            headers=PUBLIC_HEADERS,
        )

    return router
