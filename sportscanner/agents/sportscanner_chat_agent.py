"""Google ADK-powered SportScanner chat agent."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time as _time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterable, List, Literal, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from google.adk.agents import LlmAgent
from google.adk.events import Event
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.adk.tools.tool_context import ToolContext
from google.genai import types as genai_types
from pydantic import BaseModel, Field, ValidationError

from sportscanner.api.routers.geolocation.external import resolve_location_query
from sportscanner.api.routers.users.service.userService import UserService
from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details
from sportscanner.logger import logging
from sportscanner.mcp.tools.sportscanner_api import (
    find_venues_near_location_query as mcp_find_venues_near_location_query,
)
from sportscanner.mcp.tools.sportscanner_api import (
    find_venues_near_postcode as mcp_find_venues_near_postcode,
)
from sportscanner.mcp.tools.sportscanner_api import (
    validate_postcode as mcp_validate_postcode,
)
from sportscanner.agents.evals.guardrails import validate_and_patch_tool_inputs
from sportscanner.agents.evals.trajectory import (
    AgentTrajectory,
    PENDING_TOOL_STARTS,
    REQUEST_TRAJECTORY,
    ToolCallRecord,
)
from sportscanner.observability.phoenix import configure_phoenix_tracing
from sportscanner.variables import settings

try:
    from opentelemetry import trace as _otel_trace
    from openinference.semconv.trace import SpanAttributes as _OISpanAttributes
    _OI_INPUT_VALUE = _OISpanAttributes.INPUT_VALUE
    _OI_OUTPUT_VALUE = _OISpanAttributes.OUTPUT_VALUE
except Exception:
    _otel_trace = None  # type: ignore[assignment]
    _OI_INPUT_VALUE = None
    _OI_OUTPUT_VALUE = None

ChatRole = Literal["user", "assistant", "system"]

SYSTEM_PROMPT = """
You are the SportScanner Agent, an expert assistant for finding racket-sport court
availability across London.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDATORY OUTPUT RULES — apply to every single response
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. DATE TRANSPARENCY (highest priority — no exceptions, no shortcuts):
   Every response that contains availability results MUST open with a sentence
   stating which date was searched.

   WHEN YOU SHOW RESULTS FOR A DIFFERENT DATE THAN REQUESTED, the VERY FIRST
   sentence of `output` MUST follow this exact pattern:
     "No availability found for [what user asked] ([original date]).
      Here are the [earliest/evening/etc.] slots for [fallback label] ([fallback date]):"

   Example — user said "tonight" (Sat 23 May), tonight had no slots, you
   searched Sun 24 May and found slots:
     CORRECT first line:
       "No availability found for tonight (Sat 23 May). Here are the earliest
        slots for tomorrow (Sun 24 May):"
     WRONG (banned):
       Starting directly with a table of Sun 24 May results.
       Starting with "Here are the available slots..." without mentioning Sat 23 May.
       Mentioning only the fallback date without disclosing tonight had nothing.

   This rule applies even when the user's question implies a fallback is fine —
   you must ALWAYS disclose that the originally requested date/time had no results.

2. NO TRANSIENT NARRATION:
   Never start `output` with action narration. Banned opening phrases:
   "Searching for", "Fetching", "Looking up", "Checking", "Resolving",
   "Finding", "Let me", "I should", "I will", "I'll", "I am", "I'm",
   "The user asked", "Based on". Present results directly.

   LOCATION CORRECTION RULE: If geocoding returns an unexpected result,
   silently substitute a better postcode and call the search tool immediately.
   NEVER emit a message like "That location resolved to X, I'll use Y instead"
   as your final answer — that is a banned transitional thought, not a result.
   Just call the tool with the corrected postcode and show the table.

3. STRUCTURED JSON RESPONSE:
   Always return a JSON object matching exactly:
     {
       "output": "<final user-facing markdown answer>",
       "follow_up_questions": ["<question 1>", "<question 2>"]
     }
   Put only markdown text in `output`. Never reveal reasoning in `output`.

4. COMPLETE EVERY SECTION (no empty headings):
   Every section heading you write (## Heading or **Heading:**) MUST be
   followed by at least one sentence, bullet point, or table row of content.
   If you cannot fill a section, omit the heading entirely.
   BANNED: writing "**Travel Options:**" or any heading and then stopping
   without content beneath it.
   For travel/directions questions: use your general London transport knowledge
   (Tube lines, Overground, DLR, bus routes) — this is public factual
   information, not fabrication. Always include the nearest station + line and
   at least one bus route when you know the postcode/area.
   NEVER use a markdown table for travel/directions. Instead use:
     ## Venue Name
     - **Tube:** nearest station + line
     - **Bus:** relevant route(s)
     - **Rail/DLR/Overground:** if applicable
   Repeat this heading+bullets block for each venue. Do NOT squeeze directions
   into table cells — asterisks and pipes inside cells break the renderer.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Response contract:
- Use tools for factual availability, venue, and geolocation answers.
- Prefer real data from tools over guessing.
- `follow_up_questions` must contain exactly 2 concise, clickable user follow-ups.
- Follow-up questions MUST be grounded in the specific results just returned —
  name the actual venues, sport, dates, or postcodes that appeared. Never write
  generic questions like "Can you search for more venues?" or "Find courts near me."
  Examples of good follow-ups after showing Canada Water pickleball on Saturday:
    "Show me Sunday pickleball availability at Canada Water Leisure Centre"
    "Find the cheapest badminton courts near `SE1 0AA` this Saturday"
- Phrase each follow-up from the USER perspective (for example: "Show me...",
  "Find...", "What are..."). Never write assistant-perspective phrasing like
  "Would you like me..." or "Should I...".
- Never reveal internal reasoning, planning notes, or self-talk.
- Keep answers concise and direct.
- If required user input is missing, ask exactly one short clarifying question.
- When presenting findings (venues, slots, comparisons, ranked options), return
  markdown tables with a header row and separator row.
  Tables MUST start on their own line with a blank line before them.
  NEVER write `sentence.| Venue |` — always `sentence.\n\n| Venue |`.
  NEVER join two table rows as `| row1 || row2 |` — each row must be on its own line.
- Default availability table columns (in order): `Venue` | `Day` | `Time` | `Price` | `Book`
  The `Time` cell MUST always show BOTH start and end time in `HH:MM–HH:MM` format
  (e.g. `18:00–19:00`). Never show only a start time.
  The `Day` cell MUST show the full short date like `Sat 24 May` whenever results
  span multiple days OR when showing a fallback date (different from the date asked).
  When all slots are on a single expected date, a short day name (`Sat`) is fine.
  Do NOT include a `Distance` column unless the user explicitly asked to sort or
  filter by distance.
- For venue-discovery results (no slots), use: `Venue` | `Sport` | `Address`
- Always include a `Book` column with each slot's `bookingUrl` as `[Book](url)`.
  Omit only if every bookingUrl is null/empty.
- Include one short line above the table stating the search origin postcode.
  Always wrap postcodes in backticks so they render as code: e.g.
  `Distance calculated from your saved postcode: \`SE1 0AA\`` or
  `Results near \`EC2M 6SD\``.
- Keep non-table text to at most 1-2 short lines around the table.
- Use rich markdown formatting: **bold** venue names in tables and inline
  references; use `##` headings when the response covers multiple sections (e.g.
  comparing two locations); use bullet points for short lists; never write long
  unformatted prose paragraphs.
- Ensure markdown is valid and render-safe (balanced backticks/fences and escaped
  table pipes when needed).
- Headings (`##`, `###`) MUST always be on their own line, preceded by a blank
  line. NEVER place a `##` heading at the end of a sentence or on the same line
  as paragraph text. Wrong: `...near \`E16 2ZG\`. ## Venue Details:`
  Right: `...near \`E16 2ZG\`.\n\n## Venue Details:`
- If tools return no results, state that clearly and suggest one best next filter.

Location resolution rules:
- A full UK postcode looks like `SW1A 1AA` or `E16 2ZH` (letter-digit pattern).
- A partial postcode / outcode looks like `E14`, `EC2M`, `SE1`.
- Anything else (e.g. `Paddington`, `London Bridge`, `Canary Wharf`) is a place name.
- For place names or outcodes, call `sportscanner_resolve_location_query` FIRST
  to get the resolved full postcode — never call `sportscanner_validate_postcode`
  on a place name or free-text address.
- Only call `sportscanner_validate_postcode` when the input already looks like a
  full UK postcode format.
- When a user asks "near me", use their profile postcode if available in context.

Booking links:
- Booking links (`bookingUrl`) come ONLY from tool results — never construct,
  guess, or infer a booking URL yourself.
- When a user asks "how do I book", "show me the link", or similar: fetch
  availability if not already done, then present `Venue` | `Day` | `Time` | `Book`
  with actual links. No prose — just the table.

Availability query strategy:
- When a user asks about a SPECIFIC NAMED VENUE, the FIRST step is always to call
  `sportscanner_find_venues_near_location_query` with the venue name to look it up.
  Users never give the exact venue name — treat the query as a fuzzy search and
  inspect the returned venue list for a close name match.

  After the lookup, apply one of these three outcomes:

  A. GOOD MATCH FOUND — a returned venue name clearly matches what the user asked
     (e.g. user said "Canada Water" and the list contains "Canada Water Leisure
     Centre"): proceed with `sportscanner_search_single_venue_availability` using
     that venue's composite_key. This tool has no time filter and returns all
     available slots for the requested date.

  B. PARTIAL / AMBIGUOUS MATCH — the list contains one or more venues that could
     plausibly be what the user meant but are not an obvious match: ask a single
     clarifying question. Example: "I found **Britannia Leisure Centre** and
     **Better Gym Hackney** near that area — did you mean either of these?"

  C. NO MATCH — none of the returned venues resembles the venue the user named:
     STOP. Do NOT fall through to a generic area-wide search. Instead:
     - Politely state that SportScanner does not currently cover [venue name].
     - List any venues from the results that offer the same sport in the same
       area so the user has useful alternatives.
     - Offer a follow-up question (e.g. "Would you like me to check availability
       at any of these venues instead?").
     Example response for "Stratford Padel Club":
       "SportScanner doesn't currently have coverage of **Stratford Padel Club**.
        Here are padel venues nearby that are covered:
        | Venue | Address |
        | --- | --- |
        | **Padel Social Club – The O2** | Peninsula Square, SE10 0DX |
        Would you like me to check availability at one of these instead?"

  BANNED: silently showing results for a different venue than the one the user
  named without first disclosing that the requested venue wasn't found.

- Use `sportscanner_search_sport_availability` only when the query is genuinely
  area-wide with no specific venue named (e.g. "near Paddington", "near my postcode").
- When using `sportscanner_search_sport_availability` and the user has NOT specified
  a time window, set timeRange to `00:00:00`–`23:59:00` to capture all slots for
  the day. Never apply a narrow time window (e.g. evening only) unless the user
  explicitly asked for it.
- RESULT TRUNCATION (no time specified): When the user has NOT asked for a specific
  time and the tool returns more than 5 slots, show only the earliest 4–5 slots in
  the table. Below the table, add a single line:
  "More availability from HH:MM onwards — ask me to show more."
  Use the actual start time of the first omitted slot as HH:MM.
  If the user then asks to see more, show the next batch of slots.
- "This evening" = 17:00–23:59; "morning" = 06:00–12:00; "afternoon" = 12:00–17:00;
  "tonight" = current hour to 23:59 on the SAME calendar day (NEVER the next day).
- Temporal fallback: if a time-specific query (tonight, this evening, this morning)
  returns no results for the requested date, you MAY search the next day as a
  fallback — but MANDATORY OUTPUT RULE #1 applies: the disclosure sentence is
  REQUIRED before any table. You MUST NOT silently present next-day results.

Scope:
- Badminton, squash, pickleball, and padel.
- Venue discovery, nearby venues, postcode checks, and slot availability.
- Never fabricate booking links, slot times, or venue details.
""".strip()

_REQUEST_USED_TOOLS: ContextVar[Optional[list[str]]] = ContextVar(
    "sportscanner_request_used_tools",
    default=None,
)
_REQUEST_AUTHORIZATION: ContextVar[Optional[str]] = ContextVar(
    "sportscanner_request_authorization",
    default=None,
)
_AGENT_STRUCTURED_OUTPUT_STATE_KEY = "sportscanner_agent_structured_output"
# Fallback pacing used when provider/SDK does not emit partial token events.
# Kept intentionally readable so users perceive progressive streaming.
_FALLBACK_STREAM_CHUNK_SIZE = 8
_FALLBACK_STREAM_CHUNK_DELAY_SECONDS = 0.07
_DEFAULT_FOLLOW_UP_QUESTIONS = (
    "Can you narrow this to a specific date and time?",
    "Can you filter these results by distance, price, or sport?",
    "Can you check availability for one specific venue next?",
)
_TRANSIENT_REPLY_PREFIXES = (
    "searching for",
    "fetching ",
    "loading ",
    "looking up",
    "checking ",
    "resolving ",
    "finding ",
    "let me ",
    "i'll ",
    "i will ",
    "i am ",
    "i'm ",
    "i should ",
    "based on ",
    "i'll look up",
    "i will look up",
    "that location resolved",
    "the location resolved",
    "i could not resolve",
    "i wasn't able to resolve",
    "i was unable to resolve",
    "i'll use ",
    "i will use ",
    "instead, i'll",
    "instead, let me",
)
_POSTCODE_RE = re.compile(
    r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b",
    re.IGNORECASE,
)
_WITHIN_MILES_RE = re.compile(
    r"\bwithin\s+(?P<radius>\d+(?:\.\d+)?)\s*(?:mile|miles|mi)\b",
    re.IGNORECASE,
)


class AgentStructuredOutput(BaseModel):
    output: str = Field(
        ...,
        min_length=1,
        description="Final assistant markdown answer for the user.",
    )
    follow_up_questions: list[str] = Field(
        default_factory=list,
        description="Exactly two concise follow-up questions for suggested actions.",
    )


@dataclass
class AgentTurn:
    role: ChatRole
    content: str


@dataclass
class AgentResponse:
    reply: str
    used_tools: List[str]
    model: str
    follow_up_questions: list[str] = field(default_factory=list)
    ui_blocks: Optional[list[dict[str, Any]]] = None
    trajectory: Optional[AgentTrajectory] = None


@dataclass
class AgentStreamUpdate:
    event: Literal["start", "delta", "replace", "done", "tool_start"]
    delta: str = ""
    content: str = ""
    reply: str = ""
    used_tools: list[str] = field(default_factory=list)
    model: str = ""
    agent_session_id: str = ""
    follow_up_questions: list[str] = field(default_factory=list)


@dataclass
class AgentRuntime:
    runner: Runner
    session_service: InMemorySessionService


def _set_openai_runtime_env(*, api_key: str, base_url: Optional[str]) -> None:
    """
    Configure process env vars consumed by OpenAI-compatible providers.

    ADK can route `openai/<model>` via LiteLLM; both LiteLLM and OpenAI SDK
    recognize `OPENAI_API_KEY` and `OPENAI_BASE_URL` (or `OPENAI_API_BASE`).
    """
    os.environ["OPENAI_API_KEY"] = api_key

    if base_url:
        normalized_base = base_url.rstrip("/")
        os.environ["OPENAI_BASE_URL"] = normalized_base
        os.environ["OPENAI_API_BASE"] = normalized_base
        return

    # Avoid leaking stale endpoint config across hot reloads or tests.
    os.environ.pop("OPENAI_BASE_URL", None)
    os.environ.pop("OPENAI_API_BASE", None)


def _resolve_agent_api_key() -> Optional[str]:
    """
    Resolve model API key from supported env var names.

    Priority order: OpenAI → Azure → OpenRouter → generic agent key.
    """
    return (
        settings.OPENAI_API_KEY
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("AZURE_OPENAI_API_KEY")
        or settings.OPENROUTER_API_KEY
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("SPORTSCANNER_AGENT_API_KEY")
    )


def _resolve_openai_base_url() -> Optional[str]:
    return (
        settings.OPENAI_BASE_URL
        or os.getenv("OPENAI_BASE_URL")
        or os.getenv("OPENAI_API_BASE")
    )


def _normalize_messages(messages: Iterable[AgentTurn]) -> list[AgentTurn]:
    normalized: list[AgentTurn] = []
    for message in messages:
        text = message.content.strip()
        if not text:
            continue
        normalized.append(AgentTurn(role=message.role, content=text))
    return normalized


def _extract_used_tools(events: Iterable[Event]) -> list[str]:
    used: list[str] = []
    for event in events:
        for function_call in event.get_function_calls():
            tool_name = function_call.name
            if tool_name and tool_name not in used:
                used.append(tool_name)
    return used


def _build_profile_context_block(profile: dict[str, Any] | None) -> Optional[str]:
    if not profile:
        return None

    preferences = (
        profile.get("preferences")
        if isinstance(profile.get("preferences"), dict)
        else {}
    )
    postcode = preferences.get("postcode") or profile.get("postcode")
    preferred_venues = (
        preferences.get("preferredVenues") or profile.get("preferredVenues") or []
    )
    availability = preferences.get("availability") or profile.get("availability") or {}
    goals = preferences.get("goals") or profile.get("goals") or []

    lines = ["Authenticated user profile context (use when relevant):"]
    if postcode:
        lines.append(f"- postcode: {postcode}")
    if preferred_venues:
        lines.append(f"- preferred_venues: {preferred_venues}")
    if goals:
        lines.append(f"- goals: {goals}")
    if availability:
        lines.append(f"- availability_preferences: {availability}")

    if len(lines) == 1:
        return None
    return "\n".join(lines)


def _extract_event_text(event: Event) -> str:
    if not event.content or not event.content.parts:
        return ""

    parts: list[str] = []
    for part in event.content.parts:
        text = getattr(part, "text", None)
        if text:
            cleaned = str(text).strip()
            if cleaned:
                parts.append(cleaned)

    return "\n".join(parts).strip()


def _strip_wrapping_code_fence(value: str) -> str:
    stripped = value.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if len(lines) < 3:
        return stripped
    if not lines[-1].strip().startswith("```"):
        return stripped

    return "\n".join(lines[1:-1]).strip()


def _parse_structured_output_candidate(value: Any) -> Optional[AgentStructuredOutput]:
    if value is None:
        return None

    candidate: Any = value
    if isinstance(candidate, str):
        raw_text = _strip_wrapping_code_fence(candidate)
        if not raw_text:
            return None
        try:
            candidate = json.loads(raw_text)
        except json.JSONDecodeError:
            return None

    if not isinstance(candidate, dict):
        return None

    try:
        return AgentStructuredOutput.model_validate(candidate)
    except ValidationError:
        return None


def _extract_structured_output_from_events(
    events: Iterable[Event],
) -> Optional[AgentStructuredOutput]:
    event_list = list(events)

    for event in reversed(event_list):
        state_delta = getattr(event.actions, "state_delta", None) or {}
        if not isinstance(state_delta, dict):
            continue
        if _AGENT_STRUCTURED_OUTPUT_STATE_KEY not in state_delta:
            continue
        parsed = _parse_structured_output_candidate(
            state_delta.get(_AGENT_STRUCTURED_OUTPUT_STATE_KEY)
        )
        if parsed:
            return parsed

    for event in reversed(event_list):
        candidate_text = _extract_event_text(event)
        if not candidate_text:
            continue
        parsed = _parse_structured_output_candidate(candidate_text)
        if parsed:
            return parsed

    return None


def _extract_partial_json_string_value(fragment: str, key: str) -> str:
    """
    Best-effort parser for a JSON string field inside an incomplete JSON fragment.

    This enables progressive streaming when the model emits partial structured JSON.
    """
    if not fragment:
        return ""

    key_match = re.search(rf'"{re.escape(key)}"\s*:\s*"', fragment)
    if not key_match:
        return ""

    cursor = key_match.end()
    chars: list[str] = []
    length = len(fragment)

    while cursor < length:
        char = fragment[cursor]
        if char == '"':
            break

        if char != "\\":
            chars.append(char)
            cursor += 1
            continue

        cursor += 1
        if cursor >= length:
            break

        escaped = fragment[cursor]
        if escaped == "n":
            chars.append("\n")
            cursor += 1
            continue
        if escaped == "r":
            chars.append("\r")
            cursor += 1
            continue
        if escaped == "t":
            chars.append("\t")
            cursor += 1
            continue
        if escaped == "b":
            chars.append("\b")
            cursor += 1
            continue
        if escaped == "f":
            chars.append("\f")
            cursor += 1
            continue
        if escaped in {'"', "\\", "/"}:
            chars.append(escaped)
            cursor += 1
            continue
        if escaped == "u":
            if cursor + 4 >= length:
                break
            codepoint_hex = fragment[cursor + 1 : cursor + 5]
            if re.fullmatch(r"[0-9A-Fa-f]{4}", codepoint_hex):
                chars.append(chr(int(codepoint_hex, 16)))
                cursor += 5
                continue
            cursor += 1
            continue

        chars.append(escaped)
        cursor += 1

    return "".join(chars).strip()


def _extract_partial_structured_output_text(raw_text: str) -> str:
    parsed = _parse_structured_output_candidate(raw_text)
    if parsed and parsed.output:
        return parsed.output.strip()

    return _extract_partial_json_string_value(raw_text, "output")


def _normalize_follow_up_questions(
    questions: Iterable[str] | None,
) -> list[str]:
    if not questions:
        return []

    normalized: list[str] = []
    for question in questions:
        cleaned = _rewrite_follow_up_to_user_perspective(str(question))
        if not cleaned:
            continue
        if cleaned in normalized:
            continue
        normalized.append(cleaned)
    return normalized


def _rewrite_follow_up_to_user_perspective(question: str) -> str:
    cleaned = " ".join(question.strip().split())
    if not cleaned:
        return ""

    lower = cleaned.lower()
    rewritten = cleaned

    if lower.startswith("would you like me to "):
        rewritten = f"Can you {cleaned[20:]}"
    elif lower.startswith("do you want me to "):
        rewritten = f"Can you {cleaned[17:]}"
    elif lower.startswith("should i "):
        rewritten = f"Can you {cleaned[9:]}"

    rewritten = rewritten.strip()
    if not rewritten:
        return ""

    rewritten = rewritten[0].upper() + rewritten[1:]
    if not rewritten.endswith("?"):
        rewritten = f"{rewritten}?"
    return rewritten


def _ensure_two_follow_up_questions(
    questions: Iterable[str] | None,
) -> list[str]:
    normalized = _normalize_follow_up_questions(questions)

    for fallback in _DEFAULT_FOLLOW_UP_QUESTIONS:
        if len(normalized) >= 2:
            break
        if fallback in normalized:
            continue
        normalized.append(fallback)

    return normalized[:2]


def _merge_stream_text(
    previous_text: str,
    incoming_text: str,
    *,
    is_partial: bool,
) -> str:
    incoming = incoming_text.strip()
    if not incoming:
        return previous_text
    if not previous_text:
        return incoming
    if incoming.startswith(previous_text):
        return incoming
    if previous_text.startswith(incoming):
        return previous_text
    if is_partial:
        return previous_text + incoming
    return incoming


_REASONING_PREFIXES = (
    "the user asked",
    "the search returned",
    "let me",
    "i should",
    "i need to",
    "i can now",
    "i will",
    "i'll",
    "looking at",
    "key findings",
    "best options",
    "analysis:",
)
_LIST_ITEM_RE = re.compile(r"^([-*]|\d+[.)])\s+")
_ROW_SPLIT_RE = re.compile(r"\s+[—–-]\s+|\s+•\s+")
_LOCATION_WITHIN_OF_RE = re.compile(
    r"\bwithin\s+\d+(?:\.\d+)?\s*(?:mile|miles|km|kms|kilometres?|kilometers?)\s+of\s+"
    r"(?P<location>[a-zA-Z0-9\s-]{2,60})",
    re.IGNORECASE,
)
_LOCATION_NEAR_RE = re.compile(
    r"\bnear\s+(?P<location>[a-zA-Z0-9\s-]{2,60})",
    re.IGNORECASE,
)


def _normalize_for_compare(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _is_reasoning_line(value: str) -> bool:
    normalized = _normalize_for_compare(value)
    return any(normalized.startswith(prefix) for prefix in _REASONING_PREFIXES)


def _deduplicate_adjacent_sentences(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if not sentences:
        return text.strip()

    deduped: list[str] = []
    previous_normalized = ""
    for sentence in sentences:
        cleaned = sentence.strip()
        if not cleaned:
            continue
        normalized = _normalize_for_compare(cleaned)
        if normalized == previous_normalized:
            continue
        deduped.append(cleaned)
        previous_normalized = normalized

    return " ".join(deduped).strip()


def _strip_leading_reasoning(text: str) -> str:
    # Preserve table/newline layout by using line-based stripping for markdown tables.
    if _has_markdown_table(text):
        lines = [line.rstrip() for line in text.splitlines()]
        if not lines:
            return text.strip()

        kept: list[str] = []
        started = False
        for raw_line in lines:
            line = raw_line.strip()
            if not line and not started:
                continue

            if not started and _is_reasoning_line(line):
                continue

            started = True
            kept.append(raw_line)

        return "\n".join(kept).strip()

    # For plain text responses, sentence-based stripping prevents dropping the
    # entire answer when reasoning and user-facing content are on one line.
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if not sentences:
        return text.strip()

    kept_sentences: list[str] = []
    started = False
    for sentence in sentences:
        cleaned = sentence.strip()
        if not cleaned:
            continue
        if not started and _is_reasoning_line(cleaned):
            continue

        started = True
        kept_sentences.append(cleaned)

    if kept_sentences:
        return " ".join(kept_sentences).strip()

    return ""


def _has_markdown_table(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False

    for index in range(len(lines) - 1):
        header = lines[index]
        separator = lines[index + 1]
        if not (header.startswith("|") and header.endswith("|")):
            continue
        if re.match(r"^\|(\s*:?-{3,}:?\s*\|)+$", separator):
            return True
    return False


def _extract_last_table_answer(text: str) -> Optional[str]:
    lines = text.splitlines()
    if len(lines) < 2:
        return None

    last_range: Optional[tuple[int, int]] = None
    index = 0
    while index < len(lines) - 1:
        header = lines[index].strip()
        separator = lines[index + 1].strip()
        if (
            header.startswith("|")
            and header.endswith("|")
            and re.match(r"^\|(\s*:?-{3,}:?\s*\|)+$", separator)
        ):
            end = index + 2
            while end < len(lines):
                row = lines[end].strip()
                if not row.startswith("|") or not row.endswith("|"):
                    break
                end += 1
            last_range = (index, end)
            index = end
            continue
        index += 1

    if last_range is None:
        return None

    start, end = last_range
    table_lines = [line.strip() for line in lines[start:end] if line.strip()]
    if len(table_lines) < 2:
        return None

    intro_line: Optional[str] = None
    back = start - 1
    while back >= 0:
        candidate = lines[back].strip()
        if not candidate:
            back -= 1
            continue
        if candidate.startswith("|"):
            back -= 1
            continue
        if _is_reasoning_line(candidate):
            back -= 1
            continue
        intro_line = candidate
        break

    outro_line: Optional[str] = None
    forward = end
    while forward < len(lines):
        candidate = lines[forward].strip()
        if not candidate:
            forward += 1
            continue
        if candidate.startswith("|"):
            break
        if _is_reasoning_line(candidate):
            forward += 1
            continue
        outro_line = candidate
        break

    sections: list[str] = []
    if intro_line:
        sections.append(intro_line)
        sections.append("")
    sections.extend(table_lines)
    if outro_line:
        sections.extend(["", outro_line])

    return "\n".join(sections).strip()


def _render_list_as_table(text: str) -> str:
    if _has_markdown_table(text):
        return text.strip()

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return text.strip()

    intro_lines: list[str] = []
    row_lines: list[str] = []
    for line in lines:
        if _LIST_ITEM_RE.match(line):
            row_lines.append(_LIST_ITEM_RE.sub("", line).strip())
            continue
        if row_lines:
            # Ignore trailing narrative once list rows have started.
            continue
        intro_lines.append(line)

    if len(row_lines) < 2:
        return text.strip()

    split_rows = [
        [part.strip() for part in _ROW_SPLIT_RE.split(row) if part.strip()]
        for row in row_lines
    ]
    max_columns = max(len(parts) for parts in split_rows)
    max_columns = max(1, min(max_columns, 5))
    if max_columns == 1:
        headers = ["Finding"]
    else:
        headers = ["Item"] + [f"Detail {index}" for index in range(1, max_columns)]

    table_lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in split_rows:
        clipped = row[:max_columns]
        padded = clipped + [""] * (max_columns - len(clipped))
        escaped = [cell.replace("|", "\\|") for cell in padded]
        table_lines.append("| " + " | ".join(escaped) + " |")

    intro = intro_lines[-1] if intro_lines else ""
    if intro:
        return f"{intro}\n\n" + "\n".join(table_lines)
    return "\n".join(table_lines)


def _extract_tail_sentence(text: str) -> str:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text.strip())
        if sentence.strip()
    ]
    if not sentences:
        return text.strip()

    questions = [sentence for sentence in sentences if sentence.endswith("?")]
    if questions:
        return questions[-1]

    return sentences[-1]


def _extract_location_fragment_from_user_query(user_text: str) -> Optional[str]:
    normalized = " ".join(user_text.strip().split())
    if not normalized:
        return None

    for pattern in (_LOCATION_WITHIN_OF_RE, _LOCATION_NEAR_RE):
        match = pattern.search(normalized)
        if not match:
            continue
        location = match.group("location").strip(" ,.;:!?")
        if location and _normalize_for_compare(location) not in {
            "me",
            "my area",
            "my location",
            "here",
        }:
            return location
    return None


def _extract_sport_from_user_query(user_text: str) -> Optional[str]:
    lowered = user_text.lower()
    for sport in ("badminton", "squash", "pickleball", "padel"):
        if sport in lowered:
            return sport
    return None


def _extract_radius_from_user_query(user_text: str) -> float:
    match = _WITHIN_MILES_RE.search(user_text)
    if not match:
        return 10.0
    try:
        radius = float(match.group("radius"))
    except (TypeError, ValueError):
        return 10.0
    return max(0.5, min(radius, 100.0))


def _looks_like_transient_reply(reply_text: str) -> bool:
    normalized = _normalize_for_compare(reply_text)
    if not normalized:
        return True
    return normalized.startswith(_TRANSIENT_REPLY_PREFIXES)


def _looks_like_factual_venue_query(user_text: str) -> bool:
    lowered = user_text.lower()
    venue_terms = (
        "venue",
        "venues",
        "court",
        "courts",
        "availability",
        "slots",
        "postcode",
    )
    location_terms = ("near", "within", "postcode", "paddington", "canary wharf")
    return any(term in lowered for term in venue_terms) and any(
        term in lowered for term in location_terms
    )


def _should_force_factual_fallback(
    *,
    user_text: str,
    reply_text: str,
    used_tools: list[str],
) -> bool:
    if used_tools:
        return False
    if not _looks_like_factual_venue_query(user_text):
        return False

    cleaned = reply_text.strip()
    if not cleaned:
        return True
    if cleaned.endswith("?"):
        return False
    if _has_markdown_table(cleaned):
        return False
    if _looks_like_transient_reply(cleaned):
        return True
    return len(cleaned) <= 260


def _format_venues_markdown_table(
    *,
    venues: list[dict[str, Any]],
    intro: str,
    distance_origin_line: Optional[str] = None,
) -> str:
    if not venues:
        return intro

    cleaned_intro = " ".join(str(intro).strip().split())
    cleaned_origin = " ".join(str(distance_origin_line).strip().split()) if distance_origin_line else ""

    table_lines = [
        "| Venue | Distance | Sports | Address |",
        "| --- | --- | --- | --- |",
    ]
    for venue in venues:
        venue_name = str(venue.get("venue_name") or "Unknown venue").replace("|", "\\|")
        distance = venue.get("distance")
        if isinstance(distance, (int, float)):
            distance_text = f"{distance:.1f} mi"
        else:
            distance_text = "—"
        sports = venue.get("sports") or []
        sports_text = ", ".join(str(item) for item in sports) if sports else "—"
        sports_text = sports_text.replace("|", "\\|")
        address = str(venue.get("address") or "—").replace("|", "\\|")
        table_lines.append(
            f"| {venue_name} | {distance_text} | {sports_text} | {address} |"
        )

    preface_lines = [line for line in (cleaned_intro, cleaned_origin) if line]
    preface = "\n".join(preface_lines)
    return f"{preface}\n\n" + "\n".join(table_lines)


def _build_distance_origin_line(
    *,
    origin_postcode: Optional[str],
    origin_label: Optional[str] = None,
    from_saved_profile: bool = False,
) -> Optional[str]:
    postcode = " ".join(str(origin_postcode or "").strip().upper().split())
    label = " ".join(str(origin_label or "").strip().split())

    if label:
        label = label.replace("`", "\\`").replace("|", "\\|")

    if postcode and from_saved_profile:
        return f"Distance calculated from your saved postcode `{postcode}`."
    if postcode and label:
        return f"Distance calculated from `{postcode}` (resolved from {label})."
    if postcode:
        return f"Distance calculated from `{postcode}`."
    if label:
        return f"Distance calculated from {label}."
    return None


async def _build_factual_fallback_reply(
    user_text: str,
) -> Optional[tuple[str, list[str]]]:
    lower = user_text.lower()

    postcode_match = _POSTCODE_RE.search(user_text)
    if postcode_match and "validate" in lower and "postcode" in lower:
        postcode = postcode_match.group(1).upper().strip()
        validation = await mcp_validate_postcode(postcode=postcode)
        if not validation.get("valid"):
            return (
                f"`{postcode}` is not a valid postcode. Please share a full UK postcode (for example `E14 5AB`).",
                ["sportscanner_validate_postcode"],
            )
        venues = await mcp_find_venues_near_postcode(
            postcode=postcode,
            distance_miles=10.0,
        )
        sport = _extract_sport_from_user_query(user_text)
        if sport:
            venues = [
                venue
                for venue in venues
                if sport in [str(item).lower() for item in venue.get("sports") or []]
            ]
        top = venues[:12]
        intro = f"`{postcode}` is valid. Here are nearby venues:"
        distance_origin_line = _build_distance_origin_line(origin_postcode=postcode)
        return (
            _format_venues_markdown_table(
                venues=top,
                intro=intro,
                distance_origin_line=distance_origin_line,
            ),
            ["sportscanner_validate_postcode", "sportscanner_find_venues_near_postcode"],
        )

    location_query = _extract_location_fragment_from_user_query(user_text)
    if not location_query:
        return None

    radius_miles = _extract_radius_from_user_query(user_text)
    resolved = await mcp_find_venues_near_location_query(
        location_query=location_query,
        distance_miles=radius_miles,
    )
    if not resolved.get("resolved"):
        message = resolved.get("message") or (
            "I could not resolve that location. Try a fuller postcode or a known London place."
        )
        return (
            str(message),
            ["sportscanner_find_venues_near_location_query"],
        )

    venues = list(resolved.get("venues") or [])
    resolved_location = (
        resolved.get("resolved_location")
        if isinstance(resolved.get("resolved_location"), dict)
        else {}
    )
    resolved_postcode = (
        str(resolved_location.get("resolved_postcode") or "").strip() or None
    )
    resolved_origin_label = (
        str(
            resolved_location.get("display_name")
            or resolved_location.get("query")
            or location_query
        ).strip()
        or None
    )
    distance_origin_line = _build_distance_origin_line(
        origin_postcode=resolved_postcode,
        origin_label=resolved_origin_label,
    )

    sport = _extract_sport_from_user_query(user_text)
    if sport:
        venues = [
            venue
            for venue in venues
            if sport in [str(item).lower() for item in venue.get("sports") or []]
        ]

    if not venues:
        if sport:
            intro = (
                f"I couldn't find {sport} venues within {radius_miles:g} miles of "
                f"{location_query}."
            )
        else:
            intro = f"I couldn't find venues within {radius_miles:g} miles of {location_query}."
        if distance_origin_line:
            intro = f"{intro}\n{distance_origin_line}"
        return (
            intro,
            ["sportscanner_find_venues_near_location_query"],
        )

    top = venues[:12]
    sport_prefix = f"{sport} " if sport else ""
    intro = (
        f"Here are {sport_prefix}venues within {radius_miles:g} miles of "
        f"{location_query}."
    )
    return (
        _format_venues_markdown_table(
            venues=top,
            intro=intro,
            distance_origin_line=distance_origin_line,
        ),
        ["sportscanner_find_venues_near_location_query"],
    )


_TRAILING_HEADING_RE = re.compile(
    r"^(#{1,6}\s+\S.*|\*\*[^*]+\*\*:?\s*)$",
    re.IGNORECASE,
)


def _strip_trailing_empty_headings(text: str) -> str:
    """Remove headings at the very end of a response that have no content under them."""
    lines = text.rstrip().splitlines()
    while lines:
        last = lines[-1].strip()
        if _TRAILING_HEADING_RE.match(last):
            lines.pop()
            while lines and not lines[-1].strip():
                lines.pop()
        else:
            break
    return "\n".join(lines).strip()


def _normalize_inline_tables(text: str) -> str:
    # Claude (via LiteLLM) emits table rows joined on one line without newlines.
    # Three-pass normalisation:

    # Pass 1: split joined rows — "| row1 || row2 |" → "| row1 |\n| row2 |"
    normalized = re.sub(r"\|[ \t]*\|", "|\n|", text)

    # Pass 2: when prose text immediately precedes a table on the same line,
    # split them onto separate lines with a blank line between.
    lines = normalized.split("\n")
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("|"):
            result.append(line)
            continue
        first_pipe = line.find("|")
        if first_pipe > 0 and line[first_pipe:].count("|") >= 2:
            result.append(line[:first_pipe].rstrip())
            result.append("")
            result.append(line[first_pipe:])
        else:
            result.append(line)

    # Pass 3: split trailing prose glued to the end of a table row —
    # "| cell | cell |More text" → "| cell | cell |\n\nMore text"
    result2: list[str] = []
    for line in result:
        if line.startswith("|"):
            last_pipe = line.rfind("|")
            trailing = line[last_pipe + 1:].strip()
            if trailing:
                result2.append(line[:last_pipe + 1])
                result2.append("")
                result2.append(trailing)
                continue
        result2.append(line)

    return "\n".join(result2)


def _sanitize_agent_reply(text: str) -> str:
    raw = text.strip()
    if not raw:
        return raw

    # Claude (via LiteLLM) sometimes emits markdown tables inline with prose
    # or with rows joined by || instead of separated by newlines.  Normalise
    # before any further processing so _has_markdown_table sees valid tables.
    raw = _normalize_inline_tables(raw)

    # Strip leading reasoning lines while preserving the complete response body.
    # _extract_last_table_answer is intentionally not used as the primary path:
    # it only captures the last table + one surrounding line, which truncates
    # multi-section responses (e.g. a table followed by a "Travel Options" block).
    cleaned = _strip_leading_reasoning(raw)
    if not cleaned:
        return raw

    if not _has_markdown_table(cleaned):
        cleaned = _deduplicate_adjacent_sentences(cleaned)
        cleaned = _render_list_as_table(cleaned)

    cleaned = _strip_trailing_empty_headings(cleaned)
    return cleaned.strip() or raw


def _build_transcript_prompt(
    turns: list[AgentTurn],
    *,
    system_context_blocks: list[str],
) -> str:
    transcript_lines = [f"{turn.role.upper()}: {turn.content}" for turn in turns]
    sections = [
        "System context:\n" + "\n\n".join(system_context_blocks),
        "Conversation transcript (oldest first):\n" + "\n".join(transcript_lines),
        (
            "Respond as the assistant to the latest user message. Use tools for "
            "factual answers about availability, venues, and postcode proximity."
        ),
    ]
    return "\n\n".join(section for section in sections if section).strip()


class SportScannerChatAgent:
    """Reusable Google ADK chat agent backed by SportScanner MCP tools."""

    def __init__(self) -> None:
        # Ensure OpenInference/Phoenix tracing is registered from the agent path too.
        # This keeps ADK traces configured even when the agent is used outside the
        # FastAPI startup lifecycle.
        configure_phoenix_tracing()

        self._runtime_lock = asyncio.Lock()
        self._runtime: Optional[AgentRuntime] = None
        self._app_name = "sportscanner_agent"
        self._model_name = settings.SPORTSCANNER_AGENT_MODEL
        self._mcp_server_url = (
            settings.SPORTSCANNER_MCP_SERVER_URL
            or f"{(settings.API_BASE_URL or 'http://127.0.0.1:8000').rstrip('/')}/mcp"
        )

    async def _before_tool_callback(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
    ) -> Optional[dict[str, Any]]:
        used_tools = _REQUEST_USED_TOOLS.get()
        if used_tools is not None and tool.name and tool.name not in used_tools:
            used_tools.append(tool.name)

        authorization = _REQUEST_AUTHORIZATION.get()
        if authorization and "authorization" in args and not args.get("authorization"):
            args["authorization"] = authorization

        # Trajectory + guardrail wiring.
        pending = PENDING_TOOL_STARTS.get()
        if pending is not None and tool.name:
            call_id = getattr(tool_context, "function_call_id", None) or str(id(args))
            original_input = {k: v for k, v in args.items()}

            # Apply guardrails; mutate args in-place so the tool sees the fix.
            patched, guardrail_fired = await validate_and_patch_tool_inputs(
                tool.name, args
            )
            if guardrail_fired:
                args.clear()
                args.update(patched)

            pending[call_id] = {
                "start": _time.monotonic(),
                "original_input": original_input,
                "guardrail_fired": guardrail_fired,
                "patched_input": {k: v for k, v in args.items()},
            }

        if _otel_trace is not None and _OI_INPUT_VALUE:
            span = _otel_trace.get_current_span()
            if span.is_recording():
                span.set_attribute(_OI_INPUT_VALUE, json.dumps(args, default=str))

        return None

    async def _after_tool_callback(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
        tool_response: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if _otel_trace is not None and _OI_OUTPUT_VALUE:
            span = _otel_trace.get_current_span()
            if span.is_recording():
                span.set_attribute(_OI_OUTPUT_VALUE, json.dumps(tool_response, default=str))

        trajectory = REQUEST_TRAJECTORY.get()
        pending = PENDING_TOOL_STARTS.get()
        if trajectory is None or pending is None or not tool.name:
            return None

        call_id = getattr(tool_context, "function_call_id", None) or str(id(args))
        call_meta = pending.pop(call_id, {})

        start = call_meta.get("start")
        duration_ms = (_time.monotonic() - start) * 1000.0 if start else 0.0
        guardrail_fired = call_meta.get("guardrail_fired", False)
        original_input = call_meta.get("original_input") or {k: v for k, v in args.items()}
        patched_input = call_meta.get("patched_input") or {k: v for k, v in args.items()}

        error: Optional[str] = None
        if isinstance(tool_response, dict) and tool_response.get("error"):
            error = str(tool_response["error"])

        trajectory.tool_calls.append(
            ToolCallRecord(
                tool=tool.name,
                input=patched_input,
                output=tool_response,
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                duration_ms=round(duration_ms, 1),
                guardrail_fired=guardrail_fired,
                guardrail_original_input=original_input if guardrail_fired else None,
                error=error,
            )
        )
        return None

    async def _build_runtime(self) -> AgentRuntime:
        # Inject OpenRouter key early so LiteLLM picks it up for openrouter/ models.
        if settings.OPENROUTER_API_KEY:
            os.environ["OPENROUTER_API_KEY"] = settings.OPENROUTER_API_KEY

        api_key = _resolve_agent_api_key()
        if not api_key:
            raise ValueError(
                "No LLM API key configured for the SportScanner agent. "
                "Set OPENAI_API_KEY, AZURE_OPENAI_API_KEY, or OPENROUTER_API_KEY."
            )

        _set_openai_runtime_env(
            api_key=api_key,
            base_url=_resolve_openai_base_url(),
        )

        toolset = McpToolset(
            connection_params=StreamableHTTPConnectionParams(url=self._mcp_server_url),
        )
        # ADK's LLMRegistry only covers a subset of LiteLLM providers.
        # For any provider not in that list (e.g. openrouter/) we pass a
        # LiteLlm instance directly so the registry lookup is skipped.
        _REGISTRY_PREFIXES = (
            "gemini", "models/", "openai/", "azure/", "azure_ai/",
            "groq/", "anthropic/", "bedrock/", "ollama/", "ollama_chat/",
            "together_ai/", "vertex_ai/", "mistral/", "deepseek/",
            "fireworks_ai/", "cohere/", "databricks/", "ai21/",
        )
        model_param: Any = (
            self._model_name
            if any(self._model_name.startswith(p) for p in _REGISTRY_PREFIXES)
            else LiteLlm(model=self._model_name)
        )
        uk_tz = ZoneInfo("Europe/London")
        now_uk = datetime.now(uk_tz)
        date_context = (
            f"Current date and time (UK): "
            f"{now_uk.strftime('%A, %d %B %Y')} at {now_uk.strftime('%H:%M')} "
            f"({now_uk.strftime('%Z')}).\n\n"
        )
        agent = LlmAgent(
            name="sportscanner_agent",
            model=model_param,
            instruction=date_context + SYSTEM_PROMPT,
            output_schema=AgentStructuredOutput,
            output_key=_AGENT_STRUCTURED_OUTPUT_STATE_KEY,
            tools=[toolset],
            before_tool_callback=self._before_tool_callback,
            after_tool_callback=self._after_tool_callback,
        )
        session_service = InMemorySessionService()
        runner = Runner(
            app_name=self._app_name,
            agent=agent,
            session_service=session_service,
        )

        logging.info(
            "SportScanner ADK agent initialized with "
            f"model={self._model_name}, mcp={self._mcp_server_url}"
        )
        return AgentRuntime(
            runner=runner,
            session_service=session_service,
        )

    async def _get_runtime(self) -> AgentRuntime:
        if self._runtime is not None:
            return self._runtime

        async with self._runtime_lock:
            if self._runtime is None:
                self._runtime = await self._build_runtime()
        return self._runtime

    def _load_user_profile_context(self, authorization: Optional[str]) -> Optional[str]:
        if not authorization:
            return None

        try:
            access_token = get_kinde_access_token(refresh_token=authorization)
            user_details = get_kinde_user_details(access_token)
            kinde_user_id = user_details.get("id")
            if not kinde_user_id:
                return None

            profile = UserService().get_full_profile(kinde_user_id)
            return _build_profile_context_block(profile)
        except Exception as exc:
            logging.warning(
                "Unable to load authenticated user profile context for agent: "
                f"{type(exc).__name__}: {exc}"
            )
            return None

    async def _load_location_resolution_context(
        self,
        latest_user_message: str,
    ) -> Optional[str]:
        location_fragment = _extract_location_fragment_from_user_query(
            latest_user_message
        )
        if not location_fragment:
            return None

        try:
            resolved = await asyncio.to_thread(resolve_location_query, location_fragment)
        except Exception as exc:
            logging.warning(
                "Unable to resolve flexible location query for agent context: "
                f"{type(exc).__name__}: {exc}"
            )
            return None

        if not resolved.resolved_postcode:
            return None

        lines = [
            (
                "Resolved location hint from latest user query "
                "(use this unless user asks to change location):"
            ),
            f"- raw_location_query: {location_fragment}",
            f"- resolved_postcode: {resolved.resolved_postcode}",
            f"- source: {resolved.source}",
        ]
        if resolved.display_name:
            lines.append(f"- display_name: {resolved.display_name}")
        if resolved.latitude is not None and resolved.longitude is not None:
            lines.append(
                f"- coordinates: lat={resolved.latitude}, lon={resolved.longitude}"
            )

        return "\n".join(lines)

    async def chat(
        self,
        *,
        turns: list[AgentTurn],
        authorization: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AgentResponse:
        messages = _normalize_messages(turns)

        if not messages or not any(msg.role == "user" for msg in messages):
            raise ValueError("At least one user message is required.")

        runtime = await self._get_runtime()

        now_uk = datetime.now(ZoneInfo("Europe/London"))
        runtime_context = (
            "Runtime context:\n"
            f"- current_datetime_uk: {now_uk.isoformat()}\n"
            f"- timezone: Europe/London"
        )
        system_context_blocks = [runtime_context]

        profile_context = self._load_user_profile_context(authorization)
        if profile_context:
            system_context_blocks.append(profile_context)

        latest_user_message = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        location_resolution_context = await self._load_location_resolution_context(
            latest_user_message
        )
        if location_resolution_context:
            system_context_blocks.append(location_resolution_context)

        prompt_text = _build_transcript_prompt(
            messages,
            system_context_blocks=system_context_blocks,
        )
        request_message = genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=prompt_text)],
        )

        session_id = session_id or str(uuid4())
        user_id = "authenticated-user" if authorization else "anonymous-user"

        await runtime.session_service.create_session(
            app_name=self._app_name,
            user_id=user_id,
            session_id=session_id,
            state={"authorization": authorization} if authorization else None,
        )

        request_used_tools: list[str] = []
        tools_token = _REQUEST_USED_TOOLS.set(request_used_tools)
        auth_token = _REQUEST_AUTHORIZATION.set(authorization)

        # Trajectory tracking — set per-request ContextVars consumed by callbacks.
        trajectory = AgentTrajectory(query=latest_user_message)
        pending_starts: dict[str, Any] = {}
        trajectory_token = REQUEST_TRAJECTORY.set(trajectory)
        pending_token = PENDING_TOOL_STARTS.set(pending_starts)
        run_start = _time.monotonic()

        try:
            events: list[Event] = []
            async for event in runtime.runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=request_message,
            ):
                events.append(event)
        finally:
            trajectory.total_duration_ms = round(
                (_time.monotonic() - run_start) * 1000, 1
            )
            trajectory.completed_at = datetime.now(timezone.utc).isoformat()
            _REQUEST_USED_TOOLS.reset(tools_token)
            _REQUEST_AUTHORIZATION.reset(auth_token)
            REQUEST_TRAJECTORY.reset(trajectory_token)
            PENDING_TOOL_STARTS.reset(pending_token)
            try:
                await runtime.session_service.delete_session(
                    app_name=self._app_name,
                    user_id=user_id,
                    session_id=session_id,
                )
            except Exception as exc:
                logging.warning(
                    "Unable to clean up ADK session "
                    f"{session_id}: {type(exc).__name__}: {exc}"
                )

        if not events:
            raise ValueError("Agent returned no events.")

        structured_output = _extract_structured_output_from_events(events)
        follow_up_questions: list[str] = []
        reply_text = ""

        if structured_output:
            reply_text = _sanitize_agent_reply(structured_output.output)
            follow_up_questions = _ensure_two_follow_up_questions(
                structured_output.follow_up_questions
            )

        if not reply_text:
            for event in reversed(events):
                candidate = _extract_event_text(event)
                if not candidate:
                    continue
                reply_text = candidate
                if event.is_final_response():
                    break

            if not reply_text:
                raise ValueError("Agent did not produce a readable assistant response.")

            reply_text = _sanitize_agent_reply(reply_text)
            follow_up_questions = _ensure_two_follow_up_questions([])

        for tool_name in _extract_used_tools(events):
            if tool_name not in request_used_tools:
                request_used_tools.append(tool_name)

        # Transient stubs ("Fetching...", "Searching...", etc.) can slip through
        # even when tools were called — _should_force_factual_fallback skips the
        # check whenever used_tools is non-empty.  Catch them unconditionally here.
        if _looks_like_transient_reply(reply_text):
            fallback = await _build_factual_fallback_reply(latest_user_message)
            if fallback:
                reply_text, fallback_tools = fallback
                for tool_name in fallback_tools:
                    if tool_name not in request_used_tools:
                        request_used_tools.append(tool_name)
                follow_up_questions = _ensure_two_follow_up_questions(follow_up_questions)
            else:
                # No auto-resolution available — ask the user for what's missing.
                reply_text = (
                    "I need a bit more detail to search. "
                    "Could you share a postcode or London area? "
                    "For example: \"Find badminton courts near E14 5AB tonight\"."
                )
                follow_up_questions = _ensure_two_follow_up_questions([])

        if _should_force_factual_fallback(
            user_text=latest_user_message,
            reply_text=reply_text,
            used_tools=request_used_tools,
        ):
            fallback = await _build_factual_fallback_reply(latest_user_message)
            if fallback:
                reply_text, fallback_tools = fallback
                for tool_name in fallback_tools:
                    if tool_name not in request_used_tools:
                        request_used_tools.append(tool_name)
                follow_up_questions = _ensure_two_follow_up_questions(
                    follow_up_questions
                )

        trajectory.final_reply = reply_text

        return AgentResponse(
            reply=reply_text,
            used_tools=request_used_tools,
            model=self._model_name,
            follow_up_questions=follow_up_questions,
            trajectory=trajectory,
        )

    async def stream_chat(
        self,
        *,
        turns: list[AgentTurn],
        authorization: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[AgentStreamUpdate]:
        messages = _normalize_messages(turns)

        if not messages or not any(msg.role == "user" for msg in messages):
            raise ValueError("At least one user message is required.")

        runtime = await self._get_runtime()

        now_uk = datetime.now(ZoneInfo("Europe/London"))
        runtime_context = (
            "Runtime context:\n"
            f"- current_datetime_uk: {now_uk.isoformat()}\n"
            f"- timezone: Europe/London"
        )
        system_context_blocks = [runtime_context]

        profile_context = self._load_user_profile_context(authorization)
        if profile_context:
            system_context_blocks.append(profile_context)

        latest_user_message = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        location_resolution_context = await self._load_location_resolution_context(
            latest_user_message
        )
        if location_resolution_context:
            system_context_blocks.append(location_resolution_context)

        prompt_text = _build_transcript_prompt(
            messages,
            system_context_blocks=system_context_blocks,
        )
        request_message = genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=prompt_text)],
        )

        session_id = session_id or str(uuid4())
        user_id = "authenticated-user" if authorization else "anonymous-user"

        await runtime.session_service.create_session(
            app_name=self._app_name,
            user_id=user_id,
            session_id=session_id,
            state={"authorization": authorization} if authorization else None,
        )

        request_used_tools: list[str] = []
        tools_token = _REQUEST_USED_TOOLS.set(request_used_tools)
        auth_token = _REQUEST_AUTHORIZATION.set(authorization)

        raw_reply_text = ""
        emitted_reply_text = ""
        events: list[Event] = []
        stream_from_partial_events = True

        try:
            yield AgentStreamUpdate(
                event="start",
                agent_session_id=session_id,
            )
            async for event in runtime.runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=request_message,
            ):
                events.append(event)
                for function_call in event.get_function_calls():
                    tool_name = function_call.name
                    if tool_name and tool_name not in request_used_tools:
                        request_used_tools.append(tool_name)
                        yield AgentStreamUpdate(event="tool_start", delta=tool_name)

                candidate_text = _extract_event_text(event)
                if not candidate_text:
                    continue

                is_partial_event = getattr(event, "partial", False) is True

                raw_reply_text = _merge_stream_text(
                    raw_reply_text,
                    candidate_text,
                    is_partial=is_partial_event,
                )
                if not stream_from_partial_events:
                    # With structured output enabled, partial chunks are usually
                    # JSON fragments. We defer UI emission until we can stream
                    # the sanitized markdown answer from the validated final payload.
                    continue

                partial_output_text = _normalize_inline_tables(
                    _extract_partial_structured_output_text(raw_reply_text)
                )
                stream_text = partial_output_text.strip()
                if not stream_text or stream_text == emitted_reply_text:
                    continue

                if stream_text.startswith(emitted_reply_text):
                    delta = stream_text[len(emitted_reply_text) :]
                    if delta:
                        emitted_reply_text = stream_text
                        yield AgentStreamUpdate(event="delta", delta=delta)
                else:
                    emitted_reply_text = stream_text
                    yield AgentStreamUpdate(event="replace", content=stream_text)

            for tool_name in _extract_used_tools(events):
                if tool_name not in request_used_tools:
                    request_used_tools.append(tool_name)

            structured_output = _extract_structured_output_from_events(events)
            follow_up_questions: list[str] = []

            final_reply_text = ""
            if structured_output:
                final_reply_text = _sanitize_agent_reply(structured_output.output)
                follow_up_questions = _ensure_two_follow_up_questions(
                    structured_output.follow_up_questions
                )

            if not final_reply_text:
                final_reply_text = _sanitize_agent_reply(raw_reply_text)
                if not final_reply_text:
                    for event in reversed(events):
                        candidate = _extract_event_text(event)
                        if not candidate:
                            continue
                        final_reply_text = _sanitize_agent_reply(candidate)
                        if event.is_final_response():
                            break

                if not final_reply_text:
                    raise ValueError("Agent did not produce a readable assistant response.")

                follow_up_questions = _ensure_two_follow_up_questions([])

            if _should_force_factual_fallback(
                user_text=latest_user_message,
                reply_text=final_reply_text,
                used_tools=request_used_tools,
            ):
                fallback = await _build_factual_fallback_reply(latest_user_message)
                if fallback:
                    final_reply_text, fallback_tools = fallback
                    for tool_name in fallback_tools:
                        if tool_name not in request_used_tools:
                            request_used_tools.append(tool_name)
                    follow_up_questions = _ensure_two_follow_up_questions(
                        follow_up_questions
                    )

            if final_reply_text != emitted_reply_text:
                if not emitted_reply_text:
                    for index in range(0, len(final_reply_text), _FALLBACK_STREAM_CHUNK_SIZE):
                        chunk = final_reply_text[
                            index : index + _FALLBACK_STREAM_CHUNK_SIZE
                        ]
                        if not chunk:
                            continue
                        emitted_reply_text += chunk
                        yield AgentStreamUpdate(event="delta", delta=chunk)
                        await asyncio.sleep(_FALLBACK_STREAM_CHUNK_DELAY_SECONDS)
                    yield AgentStreamUpdate(
                        event="done",
                        reply=final_reply_text,
                        used_tools=request_used_tools,
                        model=self._model_name,
                        agent_session_id=session_id,
                        follow_up_questions=follow_up_questions,
                    )
                    return
                if final_reply_text.startswith(emitted_reply_text):
                    delta = final_reply_text[len(emitted_reply_text) :]
                    if delta:
                        emitted_reply_text = final_reply_text
                        yield AgentStreamUpdate(event="delta", delta=delta)
                else:
                    emitted_reply_text = final_reply_text
                    yield AgentStreamUpdate(event="replace", content=final_reply_text)

            yield AgentStreamUpdate(
                event="done",
                reply=final_reply_text,
                used_tools=request_used_tools,
                model=self._model_name,
                agent_session_id=session_id,
                follow_up_questions=follow_up_questions,
            )
        finally:
            _REQUEST_USED_TOOLS.reset(tools_token)
            _REQUEST_AUTHORIZATION.reset(auth_token)
            try:
                await runtime.session_service.delete_session(
                    app_name=self._app_name,
                    user_id=user_id,
                    session_id=session_id,
                )
            except Exception as exc:
                logging.warning(
                    "Unable to clean up ADK session "
                    f"{session_id}: {type(exc).__name__}: {exc}"
                )


sportscanner_chat_agent = SportScannerChatAgent()
