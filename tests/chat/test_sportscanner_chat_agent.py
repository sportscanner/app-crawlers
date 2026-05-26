import os

import pytest
from google.adk.events import Event
from google.genai import types as genai_types

from sportscanner.agents.sportscanner_chat_agent import (
    AgentRuntime,
    AgentTurn,
    SportScannerChatAgent,
    _REQUEST_AUTHORIZATION,
    _REQUEST_USED_TOOLS,
    _build_profile_context_block,
    _build_transcript_prompt,
    _extract_location_fragment_from_user_query,
    _extract_used_tools,
    _normalize_messages,
    _resolve_agent_api_key,
    _sanitize_agent_reply,
    _set_openai_runtime_env,
)
from sportscanner.variables import settings


def test_normalize_messages_keeps_supported_roles_only():
    messages = _normalize_messages(
        [
            AgentTurn(role="user", content="Where can I play badminton?"),
            AgentTurn(role="assistant", content="Checking now."),
            AgentTurn(role="system", content="Context message"),
            AgentTurn(role="user", content="   "),
        ]
    )

    assert len(messages) == 3
    assert [message.role for message in messages] == ["user", "assistant", "system"]
    assert [message.content for message in messages] == [
        "Where can I play badminton?",
        "Checking now.",
        "Context message",
    ]


def test_extract_used_tools_deduplicates_names():
    events = [
        Event(
            author="sportscanner_agent",
            content=genai_types.Content(
                role="model",
                parts=[
                    genai_types.Part.from_function_call(
                        name="sportscanner_list_venues",
                        args={},
                    ),
                    genai_types.Part.from_function_call(
                        name="sportscanner_list_venues",
                        args={},
                    ),
                    genai_types.Part.from_function_call(
                        name="sportscanner_search_sport_availability",
                        args={},
                    ),
                ],
            ),
        )
    ]
    used = _extract_used_tools(events)
    assert used == [
        "sportscanner_list_venues",
        "sportscanner_search_sport_availability",
    ]


def test_build_profile_context_block_uses_preferences_first():
    context = _build_profile_context_block(
        {
            "postcode": "E1 6AN",
            "preferences": {
                "postcode": "SE17TP",
                "preferredVenues": ["c3a8df88"],
                "goals": ["track"],
            },
        }
    )

    assert context is not None
    assert "SE17TP" in context
    assert "c3a8df88" in context
    assert "goals" in context


def test_build_transcript_prompt_contains_context_and_transcript():
    prompt = _build_transcript_prompt(
        [
            AgentTurn(role="user", content="Any courts near me?"),
            AgentTurn(role="assistant", content="Let me check."),
        ],
        system_context_blocks=["Runtime context:\n- timezone: Europe/London"],
    )

    assert "System context:" in prompt
    assert "Conversation transcript (oldest first):" in prompt
    assert "USER: Any courts near me?" in prompt
    assert "ASSISTANT: Let me check." in prompt


def test_extract_location_fragment_from_user_query_handles_partial_and_place_names():
    assert (
        _extract_location_fragment_from_user_query(
            "What squash venues are within 4 miles of E14?"
        )
        == "E14"
    )
    assert (
        _extract_location_fragment_from_user_query("Find courts near Paddington")
        == "Paddington"
    )
    assert _extract_location_fragment_from_user_query("Any courts near me?") is None


def test_sanitize_agent_reply_removes_leading_reasoning_and_deduplicates():
    raw = (
        "The user asked for venues near E14. Let me resolve this.\n"
        "Could you provide a full postcode? Could you provide a full postcode?"
    )
    cleaned = _sanitize_agent_reply(raw)
    assert cleaned == "Could you provide a full postcode?"


def test_sanitize_agent_reply_converts_bullets_to_markdown_table():
    raw = (
        "Here are nearby options:\n"
        "- Clapham Recreation Centre - 1.7 mi - 18:00-19:00 - £16.25\n"
        "- Britannia Leisure Centre - 3.7 mi - 19:00-19:40 - £10.20"
    )

    cleaned = _sanitize_agent_reply(raw)

    assert "| Item | Detail 1 | Detail 2 | Detail 3 |" in cleaned
    assert "| --- | --- | --- | --- |" in cleaned
    assert "Clapham Recreation Centre" in cleaned
    assert "Britannia Leisure Centre" in cleaned


def test_sanitize_agent_reply_extracts_last_table_block_only():
    raw = (
        "The search returned several venues. Let me organize this.\n"
        "| Venue | Distance |\n"
        "|---|---|\n"
        "| Draft Venue | 9.9 mi |\n\n"
        "Final answer:\n"
        "| Venue | Distance |\n"
        "|---|---|\n"
        "| Clapham Recreation Centre | 1.7 mi |\n"
    )

    cleaned = _sanitize_agent_reply(raw)

    assert "Draft Venue" not in cleaned
    assert "Clapham Recreation Centre" in cleaned
    assert cleaned.count("| Venue | Distance |") == 1


def test_set_openai_runtime_env_sets_openai_compatible_vars(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)

    _set_openai_runtime_env(
        api_key="test-key",
        base_url="https://orca-resource.services.ai.azure.com/openai/v1/",
    )

    assert os.environ["OPENAI_API_KEY"] == "test-key"
    assert (
        os.environ["OPENAI_BASE_URL"]
        == "https://orca-resource.services.ai.azure.com/openai/v1"
    )
    assert (
        os.environ["OPENAI_API_BASE"]
        == "https://orca-resource.services.ai.azure.com/openai/v1"
    )


def test_set_openai_runtime_env_clears_stale_base_url(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://stale.example.com/v1")
    monkeypatch.setenv("OPENAI_API_BASE", "https://stale.example.com/v1")

    _set_openai_runtime_env(api_key="test-key", base_url=None)

    assert os.environ["OPENAI_API_KEY"] == "test-key"
    assert "OPENAI_BASE_URL" not in os.environ
    assert "OPENAI_API_BASE" not in os.environ


def test_resolve_agent_api_key_prefers_openai_key(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("SPORTSCANNER_AGENT_API_KEY", "fallback-key")

    assert _resolve_agent_api_key() == "openai-key"


def test_resolve_agent_api_key_falls_back_to_azure_key(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.delenv("SPORTSCANNER_AGENT_API_KEY", raising=False)

    assert _resolve_agent_api_key() == "azure-key"


@pytest.mark.asyncio
async def test_chat_returns_reply_and_tools(monkeypatch):
    class FakeSessionService:
        def __init__(self):
            self.created = []
            self.deleted = []

        async def create_session(self, **kwargs):
            self.created.append(kwargs)
            return object()

        async def delete_session(self, **kwargs):
            self.deleted.append(kwargs)

    class FakeRunner:
        async def run_async(self, *, user_id, session_id, new_message):
            assert user_id == "anonymous-user"
            assert session_id.startswith("sportscanner-chat-")
            assert new_message.parts
            assert "Any badminton courts near me?" in new_message.parts[0].text
            yield Event(
                author="sportscanner_agent",
                content=genai_types.Content(
                    role="model",
                    parts=[
                        genai_types.Part.from_function_call(
                            name="sportscanner_find_venues_near_postcode",
                            args={},
                        )
                    ],
                ),
            )
            yield Event(
                author="sportscanner_agent",
                content=genai_types.Content(
                    role="model",
                    parts=[
                        genai_types.Part.from_text(
                            text="You have several options near you."
                        )
                    ],
                ),
            )

    fake_session_service = FakeSessionService()
    fake_runtime = AgentRuntime(
        runner=FakeRunner(),
        session_service=fake_session_service,
    )

    agent = SportScannerChatAgent()

    async def fake_get_runtime():
        return fake_runtime

    monkeypatch.setattr(agent, "_get_runtime", fake_get_runtime)
    monkeypatch.setattr(agent, "_load_user_profile_context", lambda auth: None)
    async def fake_location_context(latest_user_message: str):
        assert latest_user_message == "Any badminton courts near me?"
        return None

    monkeypatch.setattr(agent, "_load_location_resolution_context", fake_location_context)

    result = await agent.chat(
        turns=[AgentTurn(role="user", content="Any badminton courts near me?")],
        authorization=None,
    )

    assert result.reply == "You have several options near you."
    assert result.used_tools == ["sportscanner_find_venues_near_postcode"]
    assert result.model
    assert len(fake_session_service.created) == 1
    assert len(fake_session_service.deleted) == 1


@pytest.mark.asyncio
async def test_before_tool_callback_injects_authorization():
    class DummyTool:
        name = "sportscanner_get_user_profile"

    agent = SportScannerChatAgent()
    args = {"authorization": ""}
    used_tools: list[str] = []

    tools_token = _REQUEST_USED_TOOLS.set(used_tools)
    auth_token = _REQUEST_AUTHORIZATION.set("Bearer token-value")
    try:
        await agent._before_tool_callback(
            tool=DummyTool(),  # type: ignore[arg-type]
            args=args,
            tool_context=None,  # type: ignore[arg-type]
        )
    finally:
        _REQUEST_USED_TOOLS.reset(tools_token)
        _REQUEST_AUTHORIZATION.reset(auth_token)

    assert args["authorization"] == "Bearer token-value"
    assert used_tools == ["sportscanner_get_user_profile"]


@pytest.mark.asyncio
async def test_chat_rejects_missing_user_turn():
    agent = SportScannerChatAgent()

    with pytest.raises(ValueError, match="At least one user message"):
        await agent.chat(turns=[AgentTurn(role="assistant", content="Hello")])
