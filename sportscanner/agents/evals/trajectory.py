"""Tool trajectory recording for agent evaluation."""
from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class ToolCallRecord:
    tool: str
    input: dict[str, Any]
    output: Any
    timestamp_utc: str
    duration_ms: float
    guardrail_fired: bool = False
    guardrail_original_input: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "input": self.input,
            "output": self.output,
            "timestamp_utc": self.timestamp_utc,
            "duration_ms": round(self.duration_ms, 1),
            "guardrail_fired": self.guardrail_fired,
            "guardrail_original_input": self.guardrail_original_input,
            "error": self.error,
        }


@dataclass
class AgentTrajectory:
    query: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    final_reply: str = ""
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str = ""
    total_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "final_reply": self.final_reply,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_duration_ms": round(self.total_duration_ms, 1),
        }


# Per-request ContextVars used to thread trajectory state through ADK callbacks.
REQUEST_TRAJECTORY: ContextVar[Optional[AgentTrajectory]] = ContextVar(
    "sportscanner_eval_trajectory", default=None
)
# Maps function_call_id → {"start": monotonic_time, "input": original_args, "guardrail_fired": bool}
PENDING_TOOL_STARTS: ContextVar[Optional[dict[str, Any]]] = ContextVar(
    "sportscanner_eval_pending_starts", default=None
)


def trajectory_to_readable_text(trajectory: AgentTrajectory) -> str:
    """Format a trajectory as human-readable text for the judge prompt."""
    if not trajectory.tool_calls:
        return "  (no tools called)"

    lines: list[str] = []
    for i, call in enumerate(trajectory.tool_calls, 1):
        guardrail = " [GUARDRAIL FIRED]" if call.guardrail_fired else ""
        lines.append(f"  {i}. {call.tool}{guardrail}")

        if call.guardrail_original_input:
            lines.append(
                f"     input (original): {json.dumps(call.guardrail_original_input, default=str)[:400]}"
            )
            lines.append(
                f"     input (patched):   {json.dumps(call.input, default=str)[:400]}"
            )
        else:
            lines.append(f"     input:  {json.dumps(call.input, default=str)[:400]}")

        if call.error:
            lines.append(f"     output: ERROR — {call.error}")
        else:
            output_str = json.dumps(call.output, default=str)
            lines.append(f"     output: {output_str[:500]}")

        lines.append(f"     time:   {call.duration_ms:.0f} ms")

    return "\n".join(lines)
