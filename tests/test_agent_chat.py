"""The website's Agent mode: POST /agent/chat streams Sportscanner Agent as NDJSON.

The LLM is stubbed with an SSE stream at the HTTP layer and the court search is
stubbed, so these run offline.
"""

import json

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

import sportscanner.agents.a2a.tools as agent_tools
import sportscanner.agents.chat.endpoints as chat_router
from sportscanner.agents.a2a.agent import CourtFinderAgent, strip_ui_blocks
from sportscanner.agents.a2a.llm import LLMClient
from test_a2a_agent import SEARCH_RESULTS


def sse(*chunks):
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def delta(**fields):
    return {"choices": [{"delta": fields}]}


SEARCH_CALL = sse(
    delta(content="Let me look. "),
    delta(tool_calls=[{"index": 0, "id": "call_1", "function": {"name": "find_available_courts", "arguments": '{"sport": "badminton", '}}]),
    delta(tool_calls=[{"index": 0, "function": {"arguments": '"postcode": "E1 2AD", "date": "2026-10-24"}'}}]),
)
ANSWER = sse(
    delta(content="Whitechapel has a 19:00 slot.\n\n```openui-lang\n"),
    delta(content='root = Stack([a])\na = VenueCard("s1v1", "Closest")\n```'),
)


def make_client(monkeypatch, responses):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return responses[len(calls) - 1]

    llm = LLMClient(api_key="k", base_url="https://llm.test/v1", model="m", transport=httpx.MockTransport(handler))

    async def fake_search(**kwargs):
        return SEARCH_RESULTS

    monkeypatch.setattr(agent_tools, "_find_courts", fake_search)
    monkeypatch.setattr(chat_router, "_agent", CourtFinderAgent(llm))
    monkeypatch.setattr(chat_router.settings, "AGENT_CHAT_REQUIRE_AUTH", False)
    chat_router._recent.clear()
    app = FastAPI()
    app.include_router(chat_router.router, prefix="/agent")
    return TestClient(app), calls


def events(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_chat_streams_steps_results_and_a_generative_ui_answer(monkeypatch):
    client, calls = make_client(monkeypatch, [SEARCH_CALL, ANSWER])
    response = client.post(
        "/agent/chat",
        json={"message": "badminton near E1 2AD tonight", "conversation_id": "c1", "sport": "badminton"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    got = events(response)
    types = [e["type"] for e in got]

    # Preamble text before a tool call is retracted, then the step runs.
    assert types[:3] == ["delta", "discard_text", "step"]
    assert got[2] == {"type": "step", "id": "call_1", "label": "Searching badminton courts near E1 2AD on 2026-10-24", "status": "running"}
    search = next(e["search"] for e in got if e["type"] == "search")
    assert search["id"] == "s1" and search["venues"][0]["ref"] == "s1v1"
    assert search["venues"][0]["venue"] == "Whitechapel Sports Centre"
    done = got[-1]
    assert done["type"] == "done" and 'VenueCard("s1v1"' in done["text"]

    # Fragmented tool-call arguments were reassembled, and the LLM saw venue refs.
    tool_result = json.loads(calls[1]["messages"][-1]["content"])
    assert tool_result["venues"][0]["ref"] == "s1v1"
    # The website prompt carries the sport and UI spec; the location comes from the user.
    system = calls[0]["messages"][0]["content"]
    assert "E1 2AD" not in system
    assert "badminton" in system and "VenueCard(ref: string" in system
    assert calls[0]["stream"] is True


def test_chat_ignores_saved_postcodes_and_keeps_the_users_location_follow_up(monkeypatch):
    question = "Which area or postcode would you like to play near?"
    client, calls = make_client(monkeypatch, [sse(delta(content=question)), SEARCH_CALL, ANSWER])
    # Older website clients may still send a saved postcode. It must not become context.
    response = client.post(
        "/agent/chat",
        json={"message": "Badminton on 24 October 2026", "conversation_id": "location", "postcode": "SW1A 1AA"},
    )
    got = events(response)
    assert got[-1]["text"] == question
    assert not any(event["type"] in {"search", "step"} for event in got)
    system = calls[0]["messages"][0]["content"]
    assert "Use only locations supplied by the user in this conversation" in system
    assert "follow-up question for an area or postcode before searching" in system
    assert "SW1A 1AA" not in json.dumps(calls[0]["messages"])

    response = client.post("/agent/chat", json={"message": "Near E1 2AD", "conversation_id": "location"})
    assert any(event["type"] == "search" for event in events(response))
    history = calls[1]["messages"]
    assert {"role": "user", "content": "Badminton on 24 October 2026"} in history
    assert {"role": "assistant", "content": question} in history
    assert history[-1] == {"role": "user", "content": "Near E1 2AD"}
    assert "SW1A 1AA" not in json.dumps(history)


def test_memory_keeps_the_prose_but_drops_ui_blocks(monkeypatch):
    client, calls = make_client(monkeypatch, [SEARCH_CALL, ANSWER, sse(delta(content="Sure."))])
    client.post("/agent/chat", json={"message": "badminton tonight", "conversation_id": "c2"})
    client.post("/agent/chat", json={"message": "and later?", "conversation_id": "c2"})
    history = calls[2]["messages"]
    assert history[-2] == {"role": "assistant", "content": "Whitechapel has a 19:00 slot."}


def test_llm_errors_become_a_readable_error_event(monkeypatch):
    client, _ = make_client(monkeypatch, [httpx.Response(402, json={"error": "no credit"})])
    got = events(client.post("/agent/chat", json={"message": "hi", "conversation_id": "c3"}))
    assert got == [{"type": "error", "message": "Sportscanner Agent's LLM account has run out of credit."}]


def test_requests_are_validated_and_rate_limited(monkeypatch):
    client, _ = make_client(monkeypatch, [sse(delta(content="ok"))] * 3)
    assert client.post("/agent/chat", json={"message": "", "conversation_id": "c4"}).status_code == 422
    assert client.post("/agent/chat", json={"message": "hi", "conversation_id": "bad id!"}).status_code == 422
    monkeypatch.setattr(chat_router.settings, "AGENT_CHAT_MESSAGES_PER_HOUR", 1)
    assert client.post("/agent/chat", json={"message": "hi", "conversation_id": "c4"}).status_code == 200
    assert client.post("/agent/chat", json={"message": "hi", "conversation_id": "c4"}).status_code == 429


def test_signed_out_visitors_get_a_tighter_per_ip_limit(monkeypatch):
    client, _ = make_client(monkeypatch, [sse(delta(content="ok"))] * 3)
    monkeypatch.setattr(chat_router.settings, "AGENT_CHAT_REQUIRE_AUTH", True)
    monkeypatch.setattr(chat_router.settings, "AGENT_CHAT_ANON_MESSAGES_PER_HOUR", 1)
    ip = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
    assert client.post("/agent/chat", json={"message": "hi", "conversation_id": "c5"}, headers=ip).status_code == 200
    assert client.post("/agent/chat", json={"message": "hi", "conversation_id": "c5"}, headers=ip).status_code == 429
    other = {"x-forwarded-for": "198.51.100.2"}
    assert client.post("/agent/chat", json={"message": "hi", "conversation_id": "c6"}, headers=other).status_code == 200


def test_anonymous_use_can_be_switched_off(monkeypatch):
    client, _ = make_client(monkeypatch, [])
    monkeypatch.setattr(chat_router.settings, "AGENT_CHAT_REQUIRE_AUTH", True)
    monkeypatch.setattr(chat_router.settings, "AGENT_CHAT_ALLOW_ANONYMOUS", False)
    assert client.post("/agent/chat", json={"message": "hi", "conversation_id": "c7"}).status_code == 401


def test_strip_ui_blocks_handles_unterminated_fences():
    assert strip_ui_blocks("Hi.\n```openui-lang\nroot = Stack([])") == "Hi."


def test_fanned_out_duplicate_calls_run_once_and_show_one_step(monkeypatch):
    args = '{"sport": "badminton", "postcode": "E1 2AD", "date": "2026-10-24"}'
    spaced = '{"date": "2026-10-24", "postcode": "E1 2AD",  "sport": "badminton"}'
    fan_out = sse(
        delta(
            tool_calls=[
                {"index": i, "id": f"call_{i}", "function": {"name": "find_available_courts", "arguments": a}}
                for i, a in enumerate([args, spaced, args, args, args])
            ]
        )
    )
    client, calls = make_client(monkeypatch, [fan_out, ANSWER])
    got = events(client.post("/agent/chat", json={"message": "badminton", "conversation_id": "c8"}))
    steps = [e for e in got if e["type"] == "step"]
    assert [s["status"] for s in steps] == ["running", "done"]
    assert sum(e["type"] == "search" for e in got) == 1
    # Every call still got a tool reply, so the provider can match them up.
    tool_replies = [m for m in calls[1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_replies] == [f"call_{i}" for i in range(5)]
    assert all("duplicate_call" in m["content"] for m in tool_replies[1:])


def test_streamed_reasoning_goes_back_with_the_tool_call_turn(monkeypatch):
    def part(text):
        return {"type": "reasoning.text", "text": text, "format": "unknown", "index": 0}

    thinking_then_search = sse(
        delta(reasoning="Need ", reasoning_details=[part("Need ")]),
        delta(reasoning="a search.", reasoning_details=[part("a search.")]),
        delta(tool_calls=[{"index": 0, "id": "call_1", "function": {"name": "find_available_courts", "arguments": '{"sport": "badminton", "postcode": "E1 2AD", "date": "2026-10-24"}'}}]),
    )
    client, calls = make_client(monkeypatch, [thinking_then_search, ANSWER])
    client.post("/agent/chat", json={"message": "badminton", "conversation_id": "c9"})
    echoed = next(m for m in calls[1]["messages"] if m["role"] == "assistant")
    assert echoed["reasoning"] == "Need a search."
    assert echoed["reasoning_details"] == [part("Need a search.")]
