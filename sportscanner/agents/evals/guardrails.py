"""
Input guardrails for MCP tool calls.

Applied in before_tool_callback to catch and normalise invalid postcodes
before they reach the SportScanner API.  When a guardrail fires, the
patched args are passed to the tool and `_guardrail_fired` is set in the
trajectory so it shows up in the eval output.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# Full UK postcode: EC2M 6SD, SW1A 1AA, W1A 0AX, etc.
_FULL_POSTCODE_RE = re.compile(
    r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.IGNORECASE
)
# Outcode only: EC2M, SW1, W1A, etc.
_OUTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?$", re.IGNORECASE)

# MCP tool names that carry a postcode the LLM might get wrong.
_SEARCH_TOOL = "sportscanner_search_sport_availability"
_VENUES_NEAR_TOOL = "sportscanner_find_venues_near_postcode"
_POSTCODE_TOOLS = frozenset({_SEARCH_TOOL, _VENUES_NEAR_TOOL})


def _get_postcode(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name == _SEARCH_TOOL:
        filters = args.get("filters") or {}
        return str(filters.get("postcode") or "").strip()
    return str(args.get("postcode") or "").strip()


def _set_postcode(
    tool_name: str, args: dict[str, Any], postcode: str
) -> dict[str, Any]:
    patched = dict(args)
    if tool_name == _SEARCH_TOOL:
        patched["filters"] = {**(args.get("filters") or {}), "postcode": postcode}
    else:
        patched["postcode"] = postcode
    return patched


def _try_add_space(raw: str) -> Optional[str]:
    """EC2M6SD → EC2M 6SD (missing inward space)."""
    s = raw.upper().replace(" ", "")
    for split in (3, 4):
        if len(s) == split + 3:
            candidate = f"{s[:split]} {s[split:]}"
            if _FULL_POSTCODE_RE.match(candidate):
                return candidate
    return None


async def validate_and_patch_tool_inputs(
    tool_name: str,
    args: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """
    Check the postcode field in tool inputs and normalise when invalid.

    Returns (patched_args, guardrail_fired).  When the guardrail fires,
    `patched_args` carries the corrected postcode so the tool can succeed.
    """
    if tool_name not in _POSTCODE_TOOLS:
        return args, False

    raw = _get_postcode(tool_name, args)
    if not raw:
        return args, False

    # Already a valid full postcode — nothing to do.
    if _FULL_POSTCODE_RE.match(raw):
        return args, False

    # Strategy 1: simple space insertion (EC2M6SD → EC2M 6SD).
    normalised = _try_add_space(raw)
    if normalised:
        return _set_postcode(tool_name, args, normalised), True

    # Strategy 2: outcode or place name — resolve via the SportScanner API.
    try:
        from sportscanner.mcp.tools.sportscanner_api import (
            resolve_location_query as _resolve,
        )

        resolved = await _resolve(query=raw)
        resolved_postcode: str = (
            resolved.get("resolved_postcode") or ""
            if isinstance(resolved, dict)
            else ""
        )
        if resolved_postcode and _FULL_POSTCODE_RE.match(resolved_postcode):
            return _set_postcode(tool_name, args, resolved_postcode), True
    except Exception:
        pass

    # Could not normalise — let the tool handle the bad input and fail visibly.
    return args, False
