"""A2A court-finder agent: protocol wiring, auth, and the LLM tool loop.

The LLM provider is stubbed at the HTTP layer (httpx.MockTransport) and the court
search is stubbed at the tool boundary, so these run without network or DB.
"""

import json
import uuid

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import sportscanner.agents.a2a.tools as agent_tools
from sportscanner.agents.a2a import mount_a2a
from sportscanner.agents.a2a.llm import LLMClient

ORIGIN = "https://api.example.test"
TOKEN = "ssc_test_token"

SEARCH_RESULTS = [
    {
        "composite_key": "abc12345",
        "venue": "Whitechapel Sports Centre",
        "address": "55 Durward St, London E1 5BA",
        "distance": 0.1,
        "price": 12.8,
        "organization": "Be Well (Tower Hamlets)",
        "date": "Sat, Oct 24",
        "availability": [
            {
                "startingTime": "19:00",
                "endingTime": "20:00",
                "available": True,
                "bookingUrl": "https://example.test/book/1",
                "price": 12.8,
                "indoor": None,
            }
        ],
        "last_refreshed": "2026-10-23T14:00:00",
        "healthcheck": "ok",
    }
]


def llm_transport(script):
    """Replays scripted LLM responses and records the requests."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        status, body = script[len(calls) - 1]
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler), calls


def assistant(content=None, tool_calls=None):
    return 200, {"choices": [{"message": {"role": "assistant", "content": content, "tool_calls": tool_calls}}]}


def make_client(script, require_auth=True):
    transport, calls = llm_transport(script)
    app = FastAPI()

    async def verifier(token):
        return "user-1" if token == TOKEN else None

    mount_a2a(
        app,
        origin=ORIGIN,
        llm=LLMClient(api_key="test-key", base_url="https://llm.test/v1", model="test-model", transport=transport),
        require_auth=require_auth,
        verifier=verifier,
    )
    return TestClient(app), calls


def send(client, text, context_id=None, token=TOKEN):
    message = {"role": "ROLE_USER", "parts": [{"text": text}], "messageId": str(uuid.uuid4())}
    if context_id:
        message["contextId"] = context_id
    headers = {"A2A-Version": "1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(
        "/a2a",
        json={"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": message}},
        headers=headers,
    )


@pytest.fixture
def fake_search(monkeypatch):
    seen = []

    async def fake_find_courts(**kwargs):
        seen.append(kwargs)
        return SEARCH_RESULTS

    monkeypatch.setattr(agent_tools, "_find_courts", fake_find_courts)
    return seen


def test_agent_card_is_public_and_advertises_bearer_auth():
    client, _ = make_client([])
    response = client.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    card = response.json()
    assert card["name"] == "Sportscanner Court Finder"
    assert {i["url"] for i in card["supportedInterfaces"]} == {f"{ORIGIN}/a2a"}
    assert {i["protocolBinding"] for i in card["supportedInterfaces"]} == {"JSONRPC", "HTTP+JSON"}
    assert card["skills"][0]["id"] == "find-courts"
    assert card["securitySchemes"]["bearer"]["httpAuthSecurityScheme"]["scheme"] == "Bearer"


def test_a2a_rejects_missing_or_bad_tokens():
    client, calls = make_client([])
    assert send(client, "badminton near E1", token=None).status_code == 401
    bad = send(client, "badminton near E1", token="nope")
    assert bad.status_code == 401
    assert bad.headers["www-authenticate"].startswith("Bearer")
    assert calls == []  # never reached the LLM


def test_search_round_trip_returns_answer_and_structured_courts(fake_search):
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "find_available_courts",
            "arguments": json.dumps({"sport": "badminton", "postcode": "E1 2AD", "date": "2026-10-24", "starting_time": "18:00"}),
        },
    }
    client, calls = make_client(
        [assistant(tool_calls=[tool_call]), assistant("Whitechapel Sports Centre has 19:00 for £12.80: https://example.test/book/1")]
    )
    response = send(client, "badminton near E1 2AD tomorrow evening")
    assert response.status_code == 200, response.text
    task = response.json()["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    artifacts = {a["name"]: a for a in task["artifacts"]}
    assert "Whitechapel" in artifacts["answer"]["parts"][0]["text"]
    assert artifacts["court_availability"]["parts"][0]["data"][0]["venue"] == "Whitechapel Sports Centre"

    # The tool got the LLM's arguments, and the LLM saw a compact result.
    assert fake_search[0]["postcode"] == "E1 2AD"
    tool_message = calls[1]["messages"][-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "call_1"
    compact = json.loads(tool_message["content"])
    assert compact["venues"][0]["slots"][0]["booking_url"] == "https://example.test/book/1"
    # Tools were offered with $refs inlined.
    offered = {t["function"]["name"]: t for t in calls[0]["tools"]}
    assert "$defs" not in json.dumps(offered["find_available_courts"])
    assert set(offered) == {"find_available_courts", "resolve_place"}


def test_clarifying_question_puts_task_in_input_required_and_keeps_context(fake_search):
    client, calls = make_client([assistant("Which sport would you like to play?"), assistant("Badminton it is.")])
    first = send(client, "find me a court near E1 2AD tomorrow").json()["result"]["task"]
    assert first["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    assert first["status"]["message"]["parts"][0]["text"].endswith("?")

    send(client, "badminton", context_id=first["contextId"])
    history = calls[1]["messages"]
    assert [m["content"] for m in history if m["role"] == "user"] == ["find me a court near E1 2AD tomorrow", "badminton"]


def test_llm_billing_error_fails_task_with_safe_message():
    client, _ = make_client([(402, {"error": {"message": "Insufficient account funds"}})])
    task = send(client, "badminton near E1 2AD").json()["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    text = task["status"]["message"]["parts"][0]["text"]
    assert "run out of credit" in text
    assert "Insufficient" not in text  # provider detail is logged, not leaked


def test_auth_can_be_disabled_for_local_dev(fake_search):
    client, _ = make_client([assistant("Hello! Which sport and area?")], require_auth=False)
    assert send(client, "hi", token=None).status_code == 200


def test_tool_times_drop_timezone_offsets_and_duplicate_calls_are_not_rerun(fake_search):
    call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "find_available_courts",
            "arguments": json.dumps(
                {"sport": "badminton", "postcode": "E1 2AD", "date": "2026-10-24", "starting_time": "17:00:00-05:00"}
            ),
        },
    }
    client, calls = make_client(
        [assistant(tool_calls=[call]), assistant(tool_calls=[{**call, "id": "call_2"}]), assistant("Done.")]
    )
    send(client, "badminton near E1 2AD tomorrow evening")
    assert [s["starting_time"] for s in fake_search] == ["17:00"]  # offset stripped, repeat not re-run
    assert json.loads(calls[2]["messages"][-1]["content"])["error"] == "duplicate_call"
