"""Tools the A2A agent's LLM can call.

These wrap the same functions the MCP server exposes (see
sportscanner/mcp/registry.py), so the agent, MCP and REST all share one search
implementation. Each tool returns two things: a compact JSON-able payload for
the LLM (search results can be hundreds of slots, so they're trimmed), and the
full structured result, which the executor returns to the caller as a data
artifact.
"""

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException
from fastmcp.tools import Tool
from pydantic import ValidationError, validate_call

from sportscanner.mcp.tools.geolocation import forward_geocoding
from sportscanner.mcp.tools.search import find_available_courts

MAX_VENUES_FOR_LLM = 8
MAX_SLOTS_PER_VENUE = 6


@dataclass
class ToolOutcome:
    for_llm: Any
    structured: Any = None


@dataclass
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[[dict[str, Any], Optional[str]], Awaitable[ToolOutcome]]

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline `$defs` references; not every provider resolves `$ref`."""
    schema = deepcopy(schema)
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                merged = {**defs[ref.split("/")[-1]], **{k: v for k, v in node.items() if k != "$ref"}}
                return walk(merged)
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def compact_search_results(results: list[dict[str, Any]], ref_prefix: Optional[str] = None) -> dict[str, Any]:
    """Trim search output to what an LLM needs to answer well.

    With `ref_prefix`, each venue carries a ref ("s1v3") that generated UI can
    point at, so the page renders the real data rather than the LLM's copy."""
    venues = []
    for i, item in enumerate(results[:MAX_VENUES_FOR_LLM]):
        slots = [s for s in item.get("availability", []) if s.get("available", True)]
        venues.append(
            {
                **({"ref": f"{ref_prefix}v{i + 1}"} if ref_prefix else {}),
                "venue": item.get("venue"),
                "operator": item.get("organization"),
                "address": item.get("address"),
                "distance_miles": item.get("distance"),
                "price_from_gbp": item.get("price"),
                "open_slots": len(slots),
                "slots": [
                    {
                        "start": s.get("startingTime"),
                        "end": s.get("endingTime"),
                        "price_gbp": s.get("price"),
                        "booking_url": s.get("bookingUrl"),
                    }
                    for s in slots[:MAX_SLOTS_PER_VENUE]
                ],
                "data_may_be_stale": item.get("healthcheck") == "deprecated",
            }
        )
    return {
        "venues_with_availability": len(results),
        "venues_shown": len(venues),
        "venues": venues,
    }


_find_courts = validate_call(find_available_courts)


_CLOCK_TIME = re.compile(r"^\s*(\d{1,2}:\d{2})")


def _local_clock_time(value: Any) -> Any:
    """Keep just HH:MM. Models sometimes append a UTC offset ("17:00:00-05:00"),
    which turns the slot filter timezone-aware and silently matches nothing."""
    if isinstance(value, str) and (match := _CLOCK_TIME.match(value)):
        return match.group(1)
    return value


async def _run_find_courts(args: dict[str, Any], ref_prefix: Optional[str] = None) -> ToolOutcome:
    for key in ("starting_time", "ending_time"):
        if key in args:
            args[key] = _local_clock_time(args[key])
    try:
        results = await _find_courts(**args)
    except ValidationError as exc:
        return ToolOutcome({"error": "invalid_arguments", "detail": exc.errors(include_url=False)})
    except HTTPException as exc:
        return ToolOutcome({"error": "search_failed", "detail": exc.detail})
    except ValueError as exc:
        return ToolOutcome({"error": "invalid_arguments", "detail": str(exc)})
    return ToolOutcome(compact_search_results(results, ref_prefix), structured=results)


async def _run_resolve_place(args: dict[str, Any], ref_prefix: Optional[str] = None) -> ToolOutcome:
    place = str(args.get("place", "")).strip()
    if not place:
        return ToolOutcome({"error": "invalid_arguments", "detail": "place is required"})
    try:
        geocoded = await forward_geocoding(text=f"{place}, London", filter="countrycode:gb")
    except ValueError as exc:
        return ToolOutcome({"error": "geocoding_failed", "detail": str(exc)})
    matches = [
        {"label": r.formatted, "postcode": r.postcode, "area": r.suburb or r.city}
        for r in geocoded.results
        if r.postcode
    ][:3]
    return ToolOutcome({"matches": matches} if matches else {"error": "no_postcode_found"})


TOOLS: dict[str, AgentTool] = {
    tool.name: tool
    for tool in [
        AgentTool(
            name="find_available_courts",
            description=(find_available_courts.__doc__ or "").strip(),
            parameters=_inline_refs(Tool.from_function(find_available_courts).parameters),
            run=_run_find_courts,
        ),
        AgentTool(
            name="resolve_place",
            description=(
                "Turn a London place name (e.g. 'Stratford', 'Canary Wharf') into a UK postcode "
                "for find_available_courts. Not needed when the user already gave a postcode."
            ),
            parameters={
                "type": "object",
                "properties": {"place": {"type": "string", "description": "Neighbourhood, landmark or street"}},
                "required": ["place"],
                "additionalProperties": False,
            },
            run=_run_resolve_place,
        ),
    ]
}


async def call_tool(
    name: str, raw_arguments: str | dict[str, Any] | None, ref_prefix: Optional[str] = None
) -> ToolOutcome:
    tool = TOOLS.get(name)
    if tool is None:
        return ToolOutcome({"error": "unknown_tool", "detail": name})
    try:
        args = json.loads(raw_arguments) if isinstance(raw_arguments, str) else (raw_arguments or {})
    except json.JSONDecodeError:
        return ToolOutcome({"error": "invalid_arguments", "detail": "arguments were not valid JSON"})
    if not isinstance(args, dict):
        return ToolOutcome({"error": "invalid_arguments", "detail": "arguments must be an object"})
    return await tool.run(args, ref_prefix)
