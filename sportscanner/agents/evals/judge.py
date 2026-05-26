"""
LLM-as-judge evaluation for SportScanner agent responses.

Uses LiteLLM so it works with any model configured in settings.
The judge scores four independent rubric dimensions and returns
structured JSON for programmatic comparison and display.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from sportscanner.agents.evals.trajectory import AgentTrajectory, trajectory_to_readable_text

JUDGE_SYSTEM = (
    "You are an expert evaluator for AI agents that search sports court "
    "availability. You receive a user query, the tool calls the agent made, "
    "and the agent's final response. You evaluate the agent strictly on what "
    "the tools actually returned — never on your own knowledge of venues."
)

JUDGE_PROMPT = """
User query: {query}

Tool calls made (trajectory):
{trajectory}

Agent final response:
{response}

Score the agent on each dimension from 0 to 5 using ONLY the trajectory above:

1. response_correctness
   Did the response accurately reflect what the tools returned?
   5 = perfectly faithful to tool outputs, no fabrication
   3 = mostly accurate but minor gaps or imprecision
   1 = venues, prices, or links not present in any tool output

2. tool_efficiency
   Did the agent call the right tools and avoid redundant calls?
   5 = minimal, perfectly targeted calls
   3 = correct tools but some redundancy or an unnecessary extra call
   1 = wrong tools, missing critical tools, or excessive chaining

3. gap_handling
   When tools returned errors or empty results, did the agent admit uncertainty?
   5 = clearly stated limitations and offered a useful next step
   3 = partially acknowledged the gap
   1 = hallucinated results or silently ignored an empty/error response
   If all tools returned results: score 5 (no gap to handle).

4. completeness
   Did the response address every part of the query (sport, location, time, budget)?
   5 = all constraints answered or explicitly flagged as unresolvable
   3 = most constraints covered, minor omissions
   1 = query largely ignored or left unanswered

Return ONLY valid JSON — no prose, no markdown fences:
{{"response_correctness": <0-5>, "tool_efficiency": <0-5>, "gap_handling": <0-5>, "completeness": <0-5>, "overall": <average>, "reason": "<one concise sentence>"}}
""".strip()


async def judge_agent_response(
    query: str,
    trajectory: AgentTrajectory,
    final_response: str,
    *,
    judge_model: Optional[str] = None,
) -> dict[str, Any]:
    """
    Evaluate an agent response on four rubric dimensions using an LLM judge.

    Returns a dict with keys:
      response_correctness, tool_efficiency, gap_handling, completeness,
      overall, reason — plus `error` if the judge call itself failed.
    """
    from sportscanner.variables import settings

    model = judge_model or settings.SPORTSCANNER_JUDGE_MODEL or settings.SPORTSCANNER_AGENT_MODEL
    trajectory_text = trajectory_to_readable_text(trajectory)

    prompt = JUDGE_PROMPT.format(
        query=query,
        trajectory=trajectory_text,
        response=final_response[:2000],
    )

    try:
        import litellm  # type: ignore[import-untyped]

        response = await litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=512,
        )
        raw = (response.choices[0].message.content or "").strip()
        return _parse_judge_output(raw)
    except Exception as exc:
        return {
            "response_correctness": 0,
            "tool_efficiency": 0,
            "gap_handling": 0,
            "completeness": 0,
            "overall": 0.0,
            "reason": f"Judge call failed: {exc}",
            "error": str(exc),
        }


def _parse_judge_output(raw: str) -> dict[str, Any]:
    text = raw.strip()

    # Strip markdown code fences if the model wrapped output anyway.
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()

    try:
        data: dict[str, Any] = json.loads(text)
        required = {"response_correctness", "tool_efficiency", "gap_handling", "completeness"}
        if required.issubset(data.keys()):
            scores = [
                float(data["response_correctness"]),
                float(data["tool_efficiency"]),
                float(data["gap_handling"]),
                float(data["completeness"]),
            ]
            data["overall"] = round(sum(scores) / len(scores), 1)
            return data
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    return {
        "response_correctness": 0,
        "tool_efficiency": 0,
        "gap_handling": 0,
        "completeness": 0,
        "overall": 0.0,
        "reason": "Judge output could not be parsed.",
        "raw": raw[:500],
    }
