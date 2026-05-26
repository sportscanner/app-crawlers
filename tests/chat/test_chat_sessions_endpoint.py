from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from sportscanner.agents.sportscanner_chat_agent import AgentResponse
from sportscanner.api.root import app


def test_list_chat_sessions_returns_user_scoped_sessions(monkeypatch):
    now = datetime.now(timezone.utc)

    class FakeRepository:
        def list_sessions(self, *, kinde_user_id, limit=20):
            assert kinde_user_id == "kinde-user-1"
            assert limit == 10
            return [
                {
                    "id": "session-1",
                    "title": "Badminton near me",
                    "created_at": now,
                    "updated_at": now,
                    "message_count": 4,
                    "last_message_preview": "Any courts after 7pm?",
                }
            ]

    monkeypatch.setattr(
        "sportscanner.api.routers.chat.endpoints._require_kinde_user_id",
        lambda _: "kinde-user-1",
    )
    monkeypatch.setattr(
        "sportscanner.api.routers.chat.endpoints._chat_repository",
        FakeRepository(),
    )

    client = TestClient(app)
    response = client.get(
        "/chat/sessions?limit=10",
        headers={"Authorization": "Bearer refresh-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "session-1"
    assert body[0]["message_count"] == 4


def test_create_chat_session_returns_empty_message_list(monkeypatch):
    now = datetime.now(timezone.utc)

    class FakeRepository:
        def create_session(self, *, kinde_user_id, title=None):
            assert kinde_user_id == "kinde-user-2"
            assert title == "Morning squash"
            return SimpleNamespace(
                id="session-new",
                title="Morning squash",
                created_at=now,
                updated_at=now,
            )

    monkeypatch.setattr(
        "sportscanner.api.routers.chat.endpoints._require_kinde_user_id",
        lambda _: "kinde-user-2",
    )
    monkeypatch.setattr(
        "sportscanner.api.routers.chat.endpoints._chat_repository",
        FakeRepository(),
    )

    client = TestClient(app)
    response = client.post(
        "/chat/sessions",
        headers={"Authorization": "Bearer refresh-token"},
        json={"title": "Morning squash"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "session-new"
    assert body["messages"] == []


def test_get_chat_session_returns_messages(monkeypatch):
    now = datetime.now(timezone.utc)

    class FakeRepository:
        def get_session_with_messages(self, *, kinde_user_id, chat_session_id):
            assert kinde_user_id == "kinde-user-3"
            assert chat_session_id == "session-abc"
            return (
                SimpleNamespace(
                    id="session-abc",
                    title="Pickleball",
                    created_at=now,
                    updated_at=now,
                ),
                [
                    SimpleNamespace(
                        id=1,
                        role="user",
                        content="Find pickleball near Canary Wharf",
                        used_tools=[],
                        model=None,
                        ui_blocks=None,
                        created_at=now,
                    ),
                    SimpleNamespace(
                        id=2,
                        role="assistant",
                        content="| Venue | Distance |\n| --- | --- |\n| Poplar LC | 0.1 mi |",
                        used_tools=["sportscanner_search_sport_availability"],
                        model="openai/gpt-4.1-mini",
                        ui_blocks=[
                            {
                                "id": "venue-1",
                                "type": "venue_card",
                                "data": {"venueName": "Poplar Leisure Centre", "slots": ["07:00-09:00"]},
                            }
                        ],
                        created_at=now,
                    ),
                ],
            )

    monkeypatch.setattr(
        "sportscanner.api.routers.chat.endpoints._require_kinde_user_id",
        lambda _: "kinde-user-3",
    )
    monkeypatch.setattr(
        "sportscanner.api.routers.chat.endpoints._chat_repository",
        FakeRepository(),
    )

    client = TestClient(app)
    response = client.get(
        "/chat/sessions/session-abc",
        headers={"Authorization": "Bearer refresh-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "session-abc"
    assert len(body["messages"]) == 2
    assert body["messages"][1]["used_tools"] == ["sportscanner_search_sport_availability"]
    assert body["messages"][1]["ui_blocks"][0]["type"] == "venue_card"


def test_chat_agent_persists_exchange_and_returns_chat_session_id(monkeypatch):
    captured = {}

    class FakeRepository:
        def append_chat_exchange(
            self,
            *,
            kinde_user_id,
            user_message,
            assistant_message,
            used_tools=None,
            model=None,
            ui_blocks=None,
            chat_session_id=None,
        ):
            captured["kinde_user_id"] = kinde_user_id
            captured["user_message"] = user_message
            captured["assistant_message"] = assistant_message
            captured["used_tools"] = used_tools
            captured["model"] = model
            captured["ui_blocks"] = ui_blocks
            captured["chat_session_id"] = chat_session_id
            return "persisted-session-1"

    async def fake_chat(*, turns, authorization=None):
        assert authorization == "Bearer refresh-token"
        assert turns[-1].content == "Find badminton near me"
        return AgentResponse(
            reply="| Venue | Distance |\n| --- | --- |\n| Clapham | 1.7 mi |",
            used_tools=["sportscanner_find_venues_near_postcode"],
            model="openai/gpt-4.1-mini",
            ui_blocks=[
                {
                    "id": "venue-1",
                    "type": "venue_card",
                    "data": {"venueName": "Clapham Recreation Centre", "slots": ["18:00-19:00"]},
                }
            ],
        )

    monkeypatch.setattr(
        "sportscanner.api.routers.chat.endpoints.sportscanner_chat_agent.chat",
        fake_chat,
    )
    monkeypatch.setattr(
        "sportscanner.api.routers.chat.endpoints._resolve_kinde_user_id",
        lambda _: "kinde-user-4",
    )
    monkeypatch.setattr(
        "sportscanner.api.routers.chat.endpoints._chat_repository",
        FakeRepository(),
    )

    client = TestClient(app)
    response = client.post(
        "/chat/agent",
        headers={"Authorization": "Bearer refresh-token"},
        json={
            "chat_session_id": "existing-session-9",
            "messages": [{"role": "user", "content": "Find badminton near me"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["chat_session_id"] == "persisted-session-1"
    assert body["used_tools"] == ["sportscanner_find_venues_near_postcode"]
    assert body["ui_blocks"][0]["type"] == "venue_card"
    assert captured["chat_session_id"] == "existing-session-9"
    assert captured["kinde_user_id"] == "kinde-user-4"

