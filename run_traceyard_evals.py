"""
Run LLM-as-judge evals against the sportscanner agent and upload results to Traceyard.

Creates dataset examples in Traceyard, runs the agent against each query, scores
with the built-in LLM judge, and uploads a completed evaluation run.

Usage:
    python run_traceyard_evals.py

Prerequisites:
    - app-experiments running on http://localhost:3001
    - app-crawlers API running on http://localhost:8000
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".dev.env", override=True)

TRACEYARD_BASE = "http://localhost:3001"
AGENT_EVAL_URL = "http://localhost:8000/chat/agent/eval"
DATASET_ID = "a1d60dd0-e1df-4f52-a810-4f1256debc8e"
N_REPEATS = 5  # evaluations per example within a single run (used for agreement scoring)

TRACEYARD_USERNAME = "admin"
TRACEYARD_PASSWORD = "admin"

METRIC_LABELS: dict[str, str] = {
    "response_correctness": "Response Correctness",
    "tool_efficiency": "Tool Efficiency",
    "gap_handling": "Gap Handling",
    "completeness": "Completeness",
    "overall": "Overall",
}

EVAL_QUERIES = [
    # Core availability searches
    "Are there any badminton courts available this Saturday near Finsbury Park?",
    "Find me squash courts in East London available tomorrow evening after 6pm",
    "What pickleball venues are within 3 miles of Canary Wharf?",
    "I'm near Brixton, show me badminton slots for the next 3 days",
    "Is there anything available at Better leisure centres in Hackney this week?",
    # Padel (new sport)
    "Find padel courts near Liverpool Street this Saturday afternoon",
    "What padel venues are available in West London this weekend?",
    # Guardrail test — outcode only, no full postcode
    "Show me badminton slots near EC2M tomorrow morning before 10am",
    # Time-specific / tonight
    "Any squash courts available tonight near Shoreditch after 8pm?",
    # Specific venue lookup
    "Is Canada Water Leisure Centre available for badminton this Friday evening?",
    # Budget focused
    "Find the cheapest pickleball slots within 5 miles of SE1 this week",
    # Ambiguous — no location (gap handling test)
    "Find courts for this evening",
    # Multi-constraint
    "I want to play padel in South London this Sunday between 10am and 2pm, show me options under £20",
]


def _summarise_tool_output(output: object) -> object:
    if not isinstance(output, dict):
        return output
    if "structuredContent" in output:
        return output["structuredContent"]
    if "content" in output:
        texts = [c.get("text", "") for c in output.get("content", []) if isinstance(c, dict)]
        combined = " ".join(texts)
        return combined[:2000] if len(combined) > 2000 else combined
    return output


def _tool_trajectory_for_metadata(trajectory: dict) -> list[dict]:
    return [
        {
            "tool": tc.get("tool"),
            "input": tc.get("input"),
            "output_summary": _summarise_tool_output(tc.get("output")),
            "duration_ms": tc.get("duration_ms"),
            "error": tc.get("error"),
            "guardrail_fired": tc.get("guardrail_fired", False),
        }
        for tc in trajectory.get("tool_calls", [])
    ]


class TraceyardClient:
    def __init__(self) -> None:
        self._client = httpx.Client(timeout=30, follow_redirects=True)
        self._session_cookie: str | None = None

    def login(self) -> None:
        r = self._client.post(
            f"{TRACEYARD_BASE}/api/auth/login",
            json={"username": TRACEYARD_USERNAME, "password": TRACEYARD_PASSWORD},
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Traceyard login failed: {data}")
        # Explicitly capture the session cookie so it survives across requests.
        self._session_cookie = r.cookies.get("traceyard_session")
        print(f"Authenticated as {data['user']['username']} ({data['user']['role']})")

    def _auth_headers(self) -> dict:
        if self._session_cookie:
            return {"Cookie": f"traceyard_session={self._session_cookie}"}
        return {}

    def get(self, path: str) -> dict:
        r = self._client.get(f"{TRACEYARD_BASE}{path}", headers=self._auth_headers())
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict) -> dict:
        r = self._client.post(
            f"{TRACEYARD_BASE}{path}",
            json=body,
            headers={"Content-Type": "application/json", **self._auth_headers()},
        )
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._client.close()


def get_or_create_examples(client: TraceyardClient) -> list[dict]:
    """Ensure every query in EVAL_QUERIES has a dataset example. Create missing ones."""
    data = client.get(f"/api/datasets/{DATASET_ID}/examples?limit=500")
    existing = data.get("examples", [])

    # Build a set of query strings already in the dataset
    existing_queries: set[str] = set()
    for ex in existing:
        msgs = (ex.get("input_data") or {}).get("messages") or []
        for m in msgs:
            if m.get("role") == "user":
                existing_queries.add(m.get("content", "").strip())

    missing = [q for q in EVAL_QUERIES if q.strip() not in existing_queries]

    if not missing:
        print(f"All {len(existing)} examples already present — no creation needed.")
        return existing

    print(f"Found {len(existing)} existing examples. Creating {len(missing)} new ones...")
    created = []
    for query in missing:
        resp = client.post(
            f"/api/datasets/{DATASET_ID}/examples",
            {
                "input": {
                    "messages": [{"role": "user", "content": query}]
                },
                "output": {},
                "metadata": {"source": "sportscanner-evals"},
            },
        )
        ex = resp["example"]
        created.append(ex)
        print(f"  created {ex['id']} — {query[:60]}")

    return existing + created


async def run_eval(query: str) -> dict:
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(AGENT_EVAL_URL, json={"query": query})
        r.raise_for_status()
        return r.json()


def build_row(example_id: str, query: str, result: dict) -> dict:
    traj = result.get("trajectory") or {}
    judge = result.get("judge") or {}

    overall = float(judge.get("overall") or 0)
    feedback = judge.get("reason") or ""

    evals = [
        {
            "id": key,
            "name": METRIC_LABELS.get(key, key),
            "score": round(float(judge.get(key) or 0) / 5, 4),
            "explanation": feedback,
        }
        for key in ["response_correctness", "tool_efficiency", "gap_handling", "completeness", "overall"]
        if key in judge
    ]

    return {
        "example_id": example_id,
        "response_data": result.get("reply", ""),
        "score": round(overall / 5, 4),
        "feedback": feedback,
        "evals": evals,
        "metadata": {
            "tool_trajectory": _tool_trajectory_for_metadata(traj),
            "total_duration_ms": traj.get("total_duration_ms", 0),
            "model": result.get("model", ""),
        },
    }


async def main() -> None:
    client = TraceyardClient()
    try:
        client.login()

        examples = get_or_create_examples(client)
        # Map example public ID → query text (from input messages)
        query_by_id: dict[str, str] = {}
        for ex in examples:
            msgs = (ex.get("input_data") or {}).get("messages") or []
            query_by_id[ex["id"]] = next(
                (m.get("content", "") for m in msgs if m.get("role") == "user"), ""
            )

        total_evals = len(examples) * N_REPEATS
        print(f"\nRunning agent evals: {len(examples)} examples × {N_REPEATS} repeats = {total_evals} evaluations...\n")
        rows: list[dict] = []
        run_name = f"sportscanner-evals-{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M')}"

        eval_num = 0
        for example in examples:
            example_id = example["id"]
            query = query_by_id.get(example_id, "")

            for repeat in range(1, N_REPEATS + 1):
                eval_num += 1
                print(f"[{eval_num}/{total_evals}] repeat {repeat}/{N_REPEATS} — {query}")

                try:
                    result = await run_eval(query)
                    judge = result.get("judge") or {}
                    print(
                        f"  overall={judge.get('overall', '?')}  "
                        f"correctness={judge.get('response_correctness', '?')}  "
                        f"tools={judge.get('tool_efficiency', '?')}  "
                        f"gaps={judge.get('gap_handling', '?')}  "
                        f"completeness={judge.get('completeness', '?')}"
                    )
                    print(f"  reason: {str(judge.get('reason', ''))[:120]}")
                    rows.append(build_row(example_id, query, result))
                except Exception as exc:
                    print(f"  ERROR: {exc}")
                    rows.append({
                        "example_id": example_id,
                        "response_data": f"ERROR: {exc}",
                        "score": 0.0,
                        "feedback": str(exc),
                        "evals": [],
                        "metadata": {"error": str(exc)},
                    })

                if eval_num < total_evals:
                    time.sleep(1)

        print(f"\nUploading eval run '{run_name}' with {len(rows)} rows...")
        resp = client.post(
            f"/api/datasets/{DATASET_ID}/evaluations",
            {
                "name": run_name,
                "evaluator": "llm-judge-gemini",
                "status": "completed",
                "pass_threshold": 0.7,
                "metadata": {
                    "source": "run_traceyard_evals.py",
                    "agent_url": AGENT_EVAL_URL,
                },
                "rows": rows,
            },
        )
        run = resp.get("run", {})
        print(f"\nDone!")
        print(f"  Run ID:       {run.get('id')}")
        print(f"  Rows:         {run.get('row_count')}")
        print(f"  Scored:       {run.get('scored_count')}")
        print(f"  Avg score:    {run.get('avg_score'):.2f}")
        print(f"  Pass rate:    {run.get('pass_rate_pct')}%")
        print(f"\nOpen Traceyard → http://localhost:3001 → Datasets → {DATASET_ID}")

    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
