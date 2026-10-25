"""Sportscanner Agent: an LLM tool-use loop over Sportscanner's search.

Conversation memory is kept per A2A `contextId` in-process (bounded size and
TTL), so a follow-up like "what about Hackney?" inherits the sport and date
from the previous turn. Like the WhatsApp assistant's memory, it resets on
restart and is not shared across workers.
"""

import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Optional
from zoneinfo import ZoneInfo

from sportscanner.agents.a2a.llm import LLMClient
from sportscanner.agents.a2a.tools import TOOLS, ToolOutcome, call_tool
from sportscanner.logger import logging

MAX_TOOL_ROUNDS = 5
# Models sometimes fan out the same search many times in one turn.
MAX_CALLS_PER_ROUND = 3
HISTORY_TURNS = 8
CONTEXT_TTL_SECONDS = 30 * 60
MAX_CONTEXTS = 500

SYSTEM_PROMPT = """You are Sportscanner Agent. You help people and other agents find \
publicly bookable badminton, squash, pickleball, padel and tennis courts in London.

Now: {now} (Europe/London). Resolve relative dates like "tomorrow" or "Saturday" against this.

How to work:
- Use find_available_courts for any availability question. Never invent venues, times, prices or links.
- It needs a sport, a UK postcode and a date. If the user gives a place name instead of a postcode, \
call resolve_place first. If the sport or the location is missing and can't be inferred from the \
conversation, ask one short question instead of guessing.
- "Evening" means 17:00-22:00, "morning" 06:00-12:00, "afternoon" 12:00-17:00, "after work" from 18:00.
- Pass times as plain HH:MM London time, with no seconds or timezone offset.
- Default radius is 3 miles; widen to 5 if nothing comes back, and say you did. Never repeat \
an identical search: if it found nothing, widen it once or tell the user.

How to answer:
- Lead with the best 3-5 options: venue, distance, start times, price from, and the booking link.
- Mention when data may be stale.
- Sportscanner does not book or pay for courts. Booking happens on the operator's site.
- Plain text, concise, British English, no emojis."""


@dataclass
class AgentReply:
    text: str
    needs_input: bool = False
    search_results: list[dict[str, Any]] = field(default_factory=list)
    searches: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class ConversationStore:
    def __init__(self, max_contexts: int = MAX_CONTEXTS, ttl_seconds: int = CONTEXT_TTL_SECONDS):
        self._items: "OrderedDict[str, tuple[float, list[dict[str, Any]]]]" = OrderedDict()
        self._max = max_contexts
        self._ttl = ttl_seconds

    def get(self, context_id: Optional[str]) -> list[dict[str, Any]]:
        if not context_id or context_id not in self._items:
            return []
        stamp, turns = self._items[context_id]
        if time.monotonic() - stamp > self._ttl:
            del self._items[context_id]
            return []
        return list(turns)

    def append(self, context_id: Optional[str], user_text: str, reply_text: str) -> None:
        if not context_id:
            return
        turns = self.get(context_id) + [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": reply_text},
        ]
        self._items[context_id] = (time.monotonic(), turns[-HISTORY_TURNS * 2 :])
        self._items.move_to_end(context_id)
        while len(self._items) > self._max:
            self._items.popitem(last=False)


@dataclass
class AgentEvent:
    """One step of a run, for callers that show progress (the website's agent mode).

    - tool_start: {"id", "name", "arguments"}
    - tool_end: {"id", "name", "summary", "search"}; search is set for court searches
    - delta: {"text"}: answer text as it streams
    - discard_text: text streamed this round was preamble to tool calls, not the answer
    - done: {"reply": AgentReply}
    """

    type: str
    data: dict[str, Any] = field(default_factory=dict)


_OPENUI_BLOCK = re.compile(r"\n?```openui(?:-lang)?\n.*?(?:```|$)", re.S)


def strip_ui_blocks(text: str) -> str:
    """Drop generated-UI blocks; they hold per-turn result refs that mean nothing later."""
    return _OPENUI_BLOCK.sub("", text).strip()


def _search_summary(search: dict[str, Any]) -> str:
    count = len(search["venues"])
    if not count:
        return "No venues with open slots"
    slots = sum(len(v.get("availability") or []) for v in search["venues"])
    return f"{count} venue{'s' if count != 1 else ''}, {slots} open slot{'s' if slots != 1 else ''}"


class CourtFinderAgent:
    def __init__(self, llm: LLMClient, memory: Optional[ConversationStore] = None):
        self.llm = llm
        self.memory = memory or ConversationStore()

    async def respond(self, user_text: str, context_id: Optional[str] = None) -> AgentReply:
        reply = AgentReply(text="")
        async for event in self.run(user_text, context_id):
            if event.type == "done":
                reply = event.data["reply"]
        return reply

    async def run(
        self,
        user_text: str,
        context_id: Optional[str] = None,
        *,
        extra_system: str = "",
        stream: bool = False,
    ) -> AsyncIterator[AgentEvent]:
        now = datetime.now(ZoneInfo("Europe/London")).strftime("%A %d %B %Y, %H:%M")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT.format(now=now) + extra_system},
            *self.memory.get(context_id),
            {"role": "user", "content": user_text},
        ]
        tools = [tool.as_openai_tool() for tool in TOOLS.values()]
        reply = AgentReply(text="")

        seen_calls: set[str] = set()
        for round_no in range(MAX_TOOL_ROUNDS):
            # On the last round the model must answer with what it has.
            last_round = round_no == MAX_TOOL_ROUNDS - 1
            tool_choice = "none" if last_round else "auto"
            if stream:
                message: dict[str, Any] = {}
                streamed = False
                async for kind, value in self.llm.chat_stream(messages, tools=tools, tool_choice=tool_choice):
                    if kind == "delta":
                        streamed = True
                        yield AgentEvent("delta", {"text": value})
                    else:
                        message = value
                if streamed and message.get("tool_calls"):
                    yield AgentEvent("discard_text")
            else:
                message = await self.llm.chat(messages, tools=tools, tool_choice=tool_choice)
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                reply.text = (message.get("content") or "").strip()
                break

            # Echo the assistant turn back verbatim (minus nulls) so the
            # provider can match tool results to their call ids.
            messages.append({k: v for k, v in message.items() if v is not None})
            executed = 0
            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                args = _parse_args(fn.get("arguments"))
                call_id = call.get("id") or f"call_{len(reply.tool_calls) + 1}"
                signature = f"{name}:{json.dumps(args, sort_keys=True)}"
                search = None
                # Every call needs a tool reply, but repeats and fan-out beyond the
                # per-round cap are answered quietly: they aren't work, so they
                # don't show up as steps.
                if signature in seen_calls:
                    outcome = ToolOutcome(
                        {"error": "duplicate_call", "detail": "You already ran this exact call; the result is above. "
                         "Change the arguments or answer the user now."}
                    )
                elif executed >= MAX_CALLS_PER_ROUND:
                    outcome = ToolOutcome(
                        {"error": "too_many_calls", "detail": f"Only {MAX_CALLS_PER_ROUND} tool calls run per turn. "
                         "Use the results you have, or make one more targeted call."}
                    )
                else:
                    seen_calls.add(signature)
                    executed += 1
                    yield AgentEvent("tool_start", {"id": call_id, "name": name, "arguments": args})
                    search_id = f"s{len(reply.searches) + 1}"
                    outcome = await call_tool(name, fn.get("arguments"), ref_prefix=search_id)
                    if isinstance(outcome.structured, list):
                        search = {
                            "id": search_id,
                            "arguments": args,
                            "venues": [
                                {"ref": f"{search_id}v{i + 1}", **item} for i, item in enumerate(outcome.structured)
                            ],
                        }
                        reply.searches.append(search)
                        reply.search_results = outcome.structured
                    reply.tool_calls.append({"name": name, "arguments": fn.get("arguments")})
                    yield AgentEvent(
                        "tool_end",
                        {
                            "id": call_id,
                            "name": name,
                            "summary": _search_summary(search) if search else _tool_summary(outcome.for_llm),
                            "search": search,
                        },
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": json.dumps(outcome.for_llm, default=str),
                    }
                )
        else:
            logging.warning("A2A agent hit the tool-round limit without a final answer")
            reply.text = (
                "I couldn't finish that search. Try giving a sport, a postcode and a date, "
                "for example: badminton near E1 2AD tomorrow evening."
            )

        if not reply.text:
            reply.text = "Sorry, I couldn't put an answer together for that. Could you rephrase?"
        # A clarifying question with no search behind it means we need more input.
        reply.needs_input = not reply.tool_calls and reply.text.rstrip().endswith("?")
        self.memory.append(context_id, user_text, strip_ui_blocks(reply.text))
        yield AgentEvent("done", {"reply": reply})


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_summary(result: Any) -> str:
    if isinstance(result, dict):
        if result.get("error"):
            return "Couldn't complete this step"
        if result.get("matches"):
            first = result["matches"][0]
            return f"{first.get('postcode')} ({first.get('area') or first.get('label')})"
    return "Done"
