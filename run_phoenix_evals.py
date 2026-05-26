"""
Run LLM-as-judge evals against the sportscanner-agent-evals Phoenix dataset
and upload full results (real reply + tool trajectory) to the experiment.

Usage:
    python run_phoenix_evals.py
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".dev.env"
load_dotenv(env_path, override=True)

PHOENIX_API_KEY = os.environ["PHOENIX_API_KEY"]
PHOENIX_BASE = "https://app.phoenix.arize.com/s/yasirrkhalidd"
DATASET_ID = "RGF0YXNldDox"
EXPERIMENT_ID = "RXhwZXJpbWVudDoy"
AGENT_EVAL_URL = "http://localhost:8000/chat/agent/eval"

PHOENIX_HEADERS = {
    "Authorization": f"Bearer {PHOENIX_API_KEY}",
    "Content-Type": "application/json",
}


def phoenix_get(path: str) -> dict:
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{PHOENIX_BASE}{path}", headers=PHOENIX_HEADERS)
        r.raise_for_status()
        return r.json()


def phoenix_post(path: str, body: dict) -> dict:
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{PHOENIX_BASE}{path}", headers=PHOENIX_HEADERS, json=body)
        r.raise_for_status()
        return r.json()


async def run_eval(query: str) -> dict:
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(AGENT_EVAL_URL, json={"query": query})
        r.raise_for_status()
        return r.json()


def _tool_trajectory_for_metadata(trajectory: dict) -> list[dict]:
    """Condense tool calls into a metadata-friendly list with inputs + outputs."""
    calls = []
    for tc in trajectory.get("tool_calls", []):
        calls.append({
            "tool": tc.get("tool"),
            "input": tc.get("input"),
            "output_summary": _summarise_tool_output(tc.get("output")),
            "duration_ms": tc.get("duration_ms"),
            "error": tc.get("error"),
            "guardrail_fired": tc.get("guardrail_fired", False),
        })
    return calls


def _summarise_tool_output(output) -> object:
    """Keep the full output unless it's very large; truncate the text blobs."""
    if not isinstance(output, dict):
        return output
    # MCP tools wrap responses in content[].text — extract structured content if present
    if "structuredContent" in output:
        return output["structuredContent"]
    if "content" in output:
        texts = [c.get("text", "") for c in output.get("content", []) if isinstance(c, dict)]
        combined = " ".join(texts)
        return combined[:2000] if len(combined) > 2000 else combined
    return output


def upload_run(example_id: str, result: dict, start_iso: str, end_iso: str) -> str:
    """Upload the run output + metadata; returns the run ID."""
    traj = result.get("trajectory", {})
    judge = result.get("judge", {})

    output = {
        "reply": result.get("reply", ""),
        "used_tools": result.get("used_tools", []),
        "model": result.get("model", ""),
        "total_duration_ms": traj.get("total_duration_ms", 0),
    }
    metadata = {
        "tool_trajectory": _tool_trajectory_for_metadata(traj),
        "judge_reason": judge.get("reason", ""),
    }

    body = {
        "dataset_example_id": example_id,
        "repetition_number": 1,
        "output": output,
        "metadata": metadata,
        "error": judge.get("error"),
        "start_time": start_iso,
        "end_time": end_iso,
    }
    resp = phoenix_post(f"/v1/experiments/{EXPERIMENT_ID}/runs", body)
    return resp.get("id") or resp.get("data", {}).get("id", "")


def upload_evaluations(run_id: str, judge: dict, start_iso: str, end_iso: str) -> None:
    """Upload each rubric dimension as a separate experiment evaluation."""
    dims = ["response_correctness", "tool_efficiency", "gap_handling", "completeness", "overall"]
    for dim in dims:
        score = judge.get(dim, 0)
        phoenix_post(
            "/v1/experiment_evaluations",
            {
                "experiment_run_id": run_id,
                "name": dim,
                "annotator_kind": "LLM",
                "start_time": start_iso,
                "end_time": end_iso,
                "result": {
                    "score": float(score),
                    "label": str(int(score)) if score == int(score) else str(score),
                    "explanation": judge.get("reason", ""),
                },
            },
        )


async def main() -> None:
    print("Fetching dataset examples...")
    data = phoenix_get(f"/v1/datasets/{DATASET_ID}/examples")
    examples = data["data"]["examples"]
    print(f"Found {len(examples)} examples.\n")

    for i, example in enumerate(examples, 1):
        query = example["input"]["query"]
        example_id = example["id"]
        print(f"[{i}/{len(examples)}] {query}")

        start_ts = datetime.now(timezone.utc)
        try:
            result = await run_eval(query)
            end_ts = datetime.now(timezone.utc)
            judge = result.get("judge", {})

            print(
                f"  scores → overall={judge.get('overall'):.1f}  "
                f"correctness={judge.get('response_correctness')}  "
                f"tools={judge.get('tool_efficiency')}  "
                f"gaps={judge.get('gap_handling')}  "
                f"completeness={judge.get('completeness')}"
            )
            print(f"  reason: {judge.get('reason', '')}")

            start_iso = start_ts.isoformat()
            end_iso = end_ts.isoformat()
            run_id = upload_run(example_id, result, start_iso, end_iso)
            upload_evaluations(run_id, judge, start_iso, end_iso)
            print(f"  uploaded run {run_id[:24]}... with {len(result.get('trajectory', {}).get('tool_calls', []))} tool calls\n")

        except Exception as exc:
            end_ts = datetime.now(timezone.utc)
            print(f"  ERROR: {exc}\n")
            try:
                phoenix_post(
                    f"/v1/experiments/{EXPERIMENT_ID}/runs",
                    {
                        "dataset_example_id": example_id,
                        "repetition_number": 1,
                        "output": {},
                        "error": str(exc),
                        "start_time": start_ts.isoformat(),
                        "end_time": end_ts.isoformat(),
                    },
                )
            except Exception:
                pass

        if i < len(examples):
            time.sleep(2)

    print("Done. Open Phoenix → Datasets → sportscanner-agent-evals → Experiments.")


if __name__ == "__main__":
    asyncio.run(main())
