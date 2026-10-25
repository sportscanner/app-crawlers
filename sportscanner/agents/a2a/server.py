"""Serves Sportscanner Agent over A2A on the main FastAPI app.

Routes (alongside REST and the MCP mount):
- GET  /.well-known/agent-card.json   public Agent Card (discovery)
- POST /a2a                           A2A JSON-RPC 2.0 (SendMessage, SendStreamingMessage,
                                      GetTask, CancelTask, ...), v0.3 method names accepted too
- /a2a/v1/...                         A2A HTTP+JSON (REST) binding

Auth: the card is public. Everything under /a2a needs `Authorization: Bearer`
with a Sportscanner personal API token (ssc_...) or a Kinde access token
(public MCP is anonymous, but every A2A task runs an LLM), unless
A2A_REQUIRE_AUTH is false.
"""

from typing import Awaitable, Callable, Optional

from a2a.auth.user import User
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    DefaultServerCallContextBuilder,
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
    create_rest_routes,
)
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.constants import PROTOCOL_VERSION_1_0
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.routing import Mount

from sportscanner.agents.a2a.agent import CourtFinderAgent
from sportscanner.agents.a2a.executor import CourtFinderExecutor
from sportscanner.agents.a2a.llm import LLMClient, client_from_settings
from sportscanner.logger import logging
from sportscanner.variables import settings

A2A_PATH = "/a2a"
AGENT_VERSION = "1.0.0"

# Returns a stable caller id for a valid bearer token, else None.
TokenVerifier = Callable[[str], Awaitable[Optional[str]]]


def build_agent_card(origin: str, require_auth: bool) -> AgentCard:
    origin = origin.rstrip("/")
    card = AgentCard(
        name="Sportscanner Agent",
        description=(
            "Finds publicly bookable badminton, squash, pickleball, padel and tennis courts across "
            "London from live availability on 250+ venues. Ask in plain English; answers include "
            "venues, times, prices and the operator's booking link. It never books or pays."
        ),
        version=AGENT_VERSION,
        provider=AgentProvider(organization="Sportscanner", url="https://www.sportscanner.co.uk"),
        documentation_url=f"{origin}/agents.md",
        icon_url="https://www.sportscanner.co.uk/sportscanner.png",
        supported_interfaces=[
            AgentInterface(url=f"{origin}{A2A_PATH}", protocol_binding="JSONRPC", protocol_version=PROTOCOL_VERSION_1_0),
            AgentInterface(url=f"{origin}{A2A_PATH}", protocol_binding="HTTP+JSON", protocol_version=PROTOCOL_VERSION_1_0),
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "application/json"],
        skills=[
            AgentSkill(
                id="find-courts",
                name="Find available courts",
                description=(
                    "Search live court availability by sport, London postcode or place name, date and "
                    "time window. Returns a short answer plus structured availability with booking links."
                ),
                tags=["sports", "booking", "london", "badminton", "squash", "pickleball", "padel", "tennis"],
                examples=[
                    "Badminton near E1 2AD tomorrow evening",
                    "Any indoor padel in Canary Wharf this Saturday morning?",
                    "Cheapest tennis court near Clapham on Sunday after 4pm",
                ],
                input_modes=["text/plain"],
                output_modes=["text/plain", "application/json"],
            )
        ],
    )
    if require_auth:
        card.security_schemes["bearer"].CopyFrom(
            SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(
                    scheme="Bearer",
                    description=(
                        "A Sportscanner personal API token (ssc_..., create one in Developer mode) "
                        "or a Kinde OAuth access token. See " + f"{origin}/auth.md"
                    ),
                )
            )
        )
        card.security_requirements.append(SecurityRequirement(schemes={"bearer": StringList(list=[])}))
    return card


class _Caller(User):
    def __init__(self, principal: str):
        self._principal = principal

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def user_name(self) -> str:
        return self._principal


class _CallerContextBuilder(DefaultServerCallContextBuilder):
    """Carries the caller resolved by the auth middleware into the A2A call,
    so the task store scopes tasks per caller and memory is per caller."""

    def build(self, request: Request) -> ServerCallContext:
        context = super().build(request)
        principal = getattr(request.state, "a2a_principal", None)
        if principal:
            context.user = _Caller(principal)
        # The SDK reads A2A-Version etc. from these headers; just never keep
        # the caller's credential around in task/call state.
        headers = context.state.get("headers")
        if isinstance(headers, dict):
            headers.pop("authorization", None)
        return context


def _default_verifier() -> TokenVerifier:
    """Reuse the MCP verifier (ssc_ tokens + Kinde JWTs), built on first use."""
    verifier = None

    async def verify(token: str) -> Optional[str]:
        nonlocal verifier
        if verifier is None:
            from sportscanner.mcp.auth import HybridTokenVerifier

            verifier = HybridTokenVerifier()
        access = await verifier.verify_token(token)
        return access.client_id if access else None

    return verify


def mount_a2a(
    app: FastAPI,
    *,
    origin: Optional[str] = None,
    llm: Optional[LLMClient] = None,
    require_auth: Optional[bool] = None,
    verifier: Optional[TokenVerifier] = None,
) -> AgentCard:
    origin = (origin or settings.MCP_PUBLIC_BASE_URL).rstrip("/")
    require_auth = settings.A2A_REQUIRE_AUTH if require_auth is None else require_auth
    llm = llm or client_from_settings()
    card = build_agent_card(origin, require_auth)
    handler = DefaultRequestHandler(
        agent_executor=CourtFinderExecutor(CourtFinderAgent(llm)),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    context_builder = _CallerContextBuilder()

    if require_auth:
        verify = verifier or _default_verifier()

        @app.middleware("http")
        async def a2a_auth(request: Request, call_next):
            path = request.url.path
            if (path == A2A_PATH or path.startswith(A2A_PATH + "/")) and request.method != "OPTIONS":
                scheme, _, token = request.headers.get("authorization", "").partition(" ")
                principal = await verify(token.strip()) if scheme.lower() == "bearer" and token.strip() else None
                if not principal:
                    return JSONResponse(
                        {
                            "error": "unauthorized",
                            "detail": "Send Authorization: Bearer <Sportscanner API token>. "
                            f"See {origin}/auth.md",
                        },
                        status_code=401,
                        headers={"WWW-Authenticate": 'Bearer realm="sportscanner-a2a"'},
                    )
                request.state.a2a_principal = principal
            return await call_next(request)

    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card, cache_control="public, max-age=300"),
        jsonrpc_routes=create_jsonrpc_routes(
            handler, rpc_url=A2A_PATH, context_builder=context_builder, enable_v0_3_compat=True
        ),
        rest_routes=[
            route
            for route in create_rest_routes(handler, context_builder=context_builder, path_prefix=A2A_PATH)
            # The SDK also adds Mount("/{tenant}") for multi-tenancy. At the app
            # root it would swallow every two-segment path (/.well-known/...,
            # the MCP OAuth routes) and 404 them. We're single-tenant: drop it.
            if not isinstance(route, Mount)
        ],
    )
    logging.info(f"A2A Sportscanner Agent mounted at {A2A_PATH} (llm={llm.provider}/{llm.model}, auth={'on' if require_auth else 'off'})")
    return card
