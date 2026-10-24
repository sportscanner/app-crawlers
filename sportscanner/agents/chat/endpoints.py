"""POST /agent/chat: the court-finder agent for the website's Agent mode.

Same agent, tools and LLM as A2A (sportscanner/agents/a2a), but streamed as
NDJSON so the page can show each step as it happens and draw generative UI:

    {"type": "step", "id", "label", "status": "running"}
    {"type": "step", "id", "label", "status": "done", "summary"}
    {"type": "search", "search": {"id": "s1", "arguments", "venues": [{"ref": "s1v1", ...}]}}
    {"type": "delta", "text"}            answer text (markdown + an openui-lang block)
    {"type": "discard_text"}             text so far was preamble to a tool call
    {"type": "done", "text", "needs_input"}
    {"type": "error", "message"}

Signed-in users send their Kinde refresh token in `Authorization` (like /user).
Signed-out visitors on the homepage can use it too, like public search, unless
AGENT_CHAT_ALLOW_ANONYMOUS is off. Each message is an LLM call, so it's rate
limited: per user, and more tightly per IP for anonymous visitors.
"""

import asyncio
import hashlib
import json
import time
from collections import defaultdict, deque
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from sportscanner.agents.a2a.agent import CourtFinderAgent
from sportscanner.agents.a2a.llm import LLMError, client_from_settings
from sportscanner.agents.chat import genui
from sportscanner.api.routers.core.schemas import SportscannerSupportedSports
from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details
from sportscanner.logger import logging
from sportscanner.variables import settings

router = APIRouter()

_IDENTITY_TTL_SECONDS = 10 * 60

_agent: Optional[CourtFinderAgent] = None
_identities: dict[str, tuple[float, str]] = {}
_recent: dict[str, deque] = defaultdict(deque)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    conversation_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    sport: Optional[SportscannerSupportedSports] = None


def _get_agent() -> CourtFinderAgent:
    global _agent
    if _agent is None:
        _agent = CourtFinderAgent(client_from_settings())
    return _agent


async def _principal(authorization: Optional[str], request: Request) -> tuple[str, int]:
    """Who is asking, and their hourly message allowance."""
    if not settings.AGENT_CHAT_REQUIRE_AUTH:
        return "local", settings.AGENT_CHAT_MESSAGES_PER_HOUR
    if not authorization:
        if not settings.AGENT_CHAT_ALLOW_ANONYMOUS:
            raise HTTPException(status_code=401, detail="Sign in to use Agent mode.")
        # Render sits behind a proxy: the first X-Forwarded-For hop is the visitor.
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        ip = forwarded or (request.client.host if request.client else "unknown")
        return f"ip:{ip}", settings.AGENT_CHAT_ANON_MESSAGES_PER_HOUR
    # Exchanging the refresh token costs two Kinde calls; remember the answer briefly.
    key = hashlib.sha256(authorization.encode()).hexdigest()
    cached = _identities.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1], settings.AGENT_CHAT_MESSAGES_PER_HOUR
    try:
        access_token = await run_in_threadpool(get_kinde_access_token, authorization)
        user_id = (await run_in_threadpool(get_kinde_user_details, access_token))["id"]
    except HTTPException:
        raise HTTPException(status_code=401, detail="Your session has expired. Sign in again.")
    if len(_identities) > 5000:
        _identities.clear()
    _identities[key] = (time.monotonic() + _IDENTITY_TTL_SECONDS, user_id)
    return user_id, settings.AGENT_CHAT_MESSAGES_PER_HOUR


def _check_rate(principal: str, per_hour: int) -> None:
    window = _recent[principal]
    now = time.monotonic()
    while window and now - window[0] > 3600:
        window.popleft()
    if len(window) >= per_hour:
        raise HTTPException(status_code=429, detail="You've sent a lot of messages. Try again in a little while.")
    window.append(now)


def _step_label(name: str, args: dict[str, Any]) -> str:
    if name == "resolve_place":
        return f"Finding a postcode for {args.get('place') or 'that place'}"
    if name == "find_available_courts":
        sport = f"{args['sport']} courts" if args.get("sport") else "courts"
        where = f" near {args['postcode']}" if args.get("postcode") else ""
        when = f" on {args['date']}" if args.get("date") else ""
        start, end = args.get("starting_time"), args.get("ending_time")
        hours = f", {str(start)[:5]}–{str(end)[:5]}" if start and end else ""
        radius = f" within {args['radius_miles']:g} mi" if isinstance(args.get("radius_miles"), (int, float)) else ""
        return f"Searching {sport}{where}{radius}{when}{hours}"
    return "Working"


def _line(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, default=str, ensure_ascii=False) + "\n").encode()


async def _events(body: ChatRequest, user_id: str) -> AsyncIterator[bytes]:
    labels: dict[str, str] = {}
    try:
        async for event in _get_agent().run(
            body.message.strip(),
            context_id=f"web:{user_id}:{body.conversation_id}",
            extra_system=genui.system_extra(sport=body.sport.value if body.sport else None),
            stream=True,
        ):
            data = event.data
            if event.type == "tool_start":
                labels[data["id"]] = _step_label(data["name"], data["arguments"])
                yield _line({"type": "step", "id": data["id"], "label": labels[data["id"]], "status": "running"})
            elif event.type == "tool_end":
                if data.get("search"):
                    yield _line({"type": "search", "search": data["search"]})
                yield _line(
                    {
                        "type": "step",
                        "id": data["id"],
                        "label": labels.get(data["id"], "Working"),
                        "status": "done",
                        "summary": data["summary"],
                    }
                )
            elif event.type == "delta":
                yield _line({"type": "delta", "text": data["text"]})
            elif event.type == "discard_text":
                yield _line({"type": "discard_text"})
            elif event.type == "done":
                reply = data["reply"]
                yield _line({"type": "done", "text": reply.text, "needs_input": reply.needs_input})
    except LLMError as exc:
        logging.error(f"Agent chat LLM error: {exc}")
        yield _line({"type": "error", "message": exc.public_message})
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # pragma: no cover - defensive: never leave the page hanging
        logging.exception(f"Agent chat failed: {exc}")
        yield _line({"type": "error", "message": "Something went wrong. Try again."})


@router.post("/chat")
async def agent_chat(body: ChatRequest, request: Request, Authorization: Optional[str] = Header(default=None)):
    user_id, per_hour = await _principal(Authorization, request)
    _check_rate(user_id, per_hour)
    return StreamingResponse(
        _events(body, user_id),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
