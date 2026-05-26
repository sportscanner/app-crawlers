import json

from fastapi.testclient import TestClient

from sportscanner.agents.sportscanner_chat_agent import AgentResponse, AgentStreamUpdate
from sportscanner.api.root import app


def test_chat_endpoint_success(monkeypatch):
    async def fake_chat(*, turns, authorization=None):
        assert authorization == "Bearer refresh-token"
        assert turns[-1].content == "Find squash tomorrow near me"
        return AgentResponse(
            reply="I found 4 squash options tomorrow within 5 miles.",
            used_tools=["sportscanner_find_venues_near_postcode"],
            model="gpt-4.1-mini",
            follow_up_questions=[
                "Would you like me to filter by time window?",
                "Should I sort those by distance or price?",
            ],
        )

    monkeypatch.setattr(
        "sportscanner.api.routers.chat.endpoints.sportscanner_chat_agent.chat",
        fake_chat,
    )

    client = TestClient(app)
    response = client.post(
        "/chat/agent",
        headers={"Authorization": "Bearer refresh-token"},
        json={
            "messages": [
                {"role": "user", "content": "Find squash tomorrow near me"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["reply"].startswith("I found 4 squash options")
    assert response.json()["used_tools"] == ["sportscanner_find_venues_near_postcode"]
    assert response.json()["follow_up_questions"] == [
        "Would you like me to filter by time window?",
        "Should I sort those by distance or price?",
    ]


def test_chat_endpoint_returns_400_on_validation_error(monkeypatch):
    async def fake_chat(*, turns, authorization=None):
        raise ValueError("At least one user message is required.")

    monkeypatch.setattr(
        "sportscanner.api.routers.chat.endpoints.sportscanner_chat_agent.chat",
        fake_chat,
    )

    client = TestClient(app)
    response = client.post(
        "/chat/agent",
        json={
            "messages": [
                {"role": "assistant", "content": "No user turn provided"},
            ]
        },
    )

    assert response.status_code == 400
    assert "At least one user message" in response.json()["detail"]


def _parse_sse_frames(raw: str):
    frames = [frame.strip() for frame in raw.split("\n\n") if frame.strip()]
    events = []
    for frame in frames:
        event_name = None
        data_blob = None
        for line in frame.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_blob = line.split(":", 1)[1].strip()
        if event_name and data_blob:
            events.append((event_name, json.loads(data_blob)))
    return events


def test_chat_stream_endpoint_success(monkeypatch):
    async def fake_stream_chat(*, turns, authorization=None):
        assert authorization == "Bearer refresh-token"
        assert turns[-1].content == "Find squash tomorrow near me"
        yield AgentStreamUpdate(event="start", agent_session_id="sportscanner-chat-test")
        yield AgentStreamUpdate(event="delta", delta="| Venue | Distance |\n| --- | --- |\n")
        yield AgentStreamUpdate(event="delta", delta="| Oasis Sports Centre | 1.2 mi |")
        yield AgentStreamUpdate(
            event="done",
            reply="| Venue | Distance |\n| --- | --- |\n| Oasis Sports Centre | 1.2 mi |",
            used_tools=["sportscanner_find_venues_near_postcode"],
            model="gpt-4.1-mini",
            agent_session_id="sportscanner-chat-test",
            follow_up_questions=[
                "Would you like evening-only slots?",
                "Should I also include pickleball nearby?",
            ],
        )

    monkeypatch.setattr(
        "sportscanner.api.routers.chat.endpoints.sportscanner_chat_agent.stream_chat",
        fake_stream_chat,
    )

    client = TestClient(app)
    response = client.post(
        "/chat/agent/stream",
        headers={"Authorization": "Bearer refresh-token"},
        json={
            "messages": [
                {"role": "user", "content": "Find squash tomorrow near me"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse_frames(response.text)
    event_names = [event_name for event_name, _ in events]
    assert "start" in event_names
    assert "delta" in event_names
    assert "meta" in event_names
    assert "done" in event_names

    start_payload = next(payload for event_name, payload in events if event_name == "start")
    assert start_payload["agent_session_id"] == "sportscanner-chat-test"

    done_payload = next(payload for event_name, payload in events if event_name == "done")
    assert done_payload["model"] == "gpt-4.1-mini"
    assert done_payload["used_tools"] == ["sportscanner_find_venues_near_postcode"]
    assert "| Venue | Distance |" in done_payload["reply"]
    assert done_payload["agent_session_id"] == "sportscanner-chat-test"
    assert done_payload["follow_up_questions"] == [
        "Would you like evening-only slots?",
        "Should I also include pickleball nearby?",
    ]


def test_chat_stream_endpoint_returns_error_event(monkeypatch):
    async def fake_stream_chat(*, turns, authorization=None):
        raise ValueError("At least one user message is required.")
        if False:
            yield AgentStreamUpdate(event="done")

    monkeypatch.setattr(
        "sportscanner.api.routers.chat.endpoints.sportscanner_chat_agent.stream_chat",
        fake_stream_chat,
    )

    client = TestClient(app)
    response = client.post(
        "/chat/agent/stream",
        json={
            "messages": [
                {"role": "assistant", "content": "No user turn provided"},
            ]
        },
    )

    assert response.status_code == 200
    events = _parse_sse_frames(response.text)
    error_payload = next(payload for event_name, payload in events if event_name == "error")
    assert error_payload["status_code"] == 400
    assert "At least one user message" in error_payload["error"]
