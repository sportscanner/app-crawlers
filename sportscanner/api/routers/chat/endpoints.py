import json
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

try:
    from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes

    _OI_SPAN_KIND_KEY = SpanAttributes.OPENINFERENCE_SPAN_KIND
    _OI_AGENT_SPAN_KIND = OpenInferenceSpanKindValues.AGENT.value
    _OI_INPUT_VALUE_KEY = SpanAttributes.INPUT_VALUE
    _OI_OUTPUT_VALUE_KEY = SpanAttributes.OUTPUT_VALUE
    _OI_SESSION_ID_KEY = SpanAttributes.SESSION_ID
except Exception:
    _OI_SPAN_KIND_KEY = None
    _OI_AGENT_SPAN_KIND = None
    _OI_INPUT_VALUE_KEY = None
    _OI_OUTPUT_VALUE_KEY = None
    _OI_SESSION_ID_KEY = None

from sportscanner.agents.sportscanner_chat_agent import (
    AgentTurn,
    sportscanner_chat_agent,  # noqa: F401 — used by eval endpoint
)
from sportscanner.core.kinde.auth import get_kinde_access_token, get_kinde_user_details
from sportscanner.logger import logging
from sportscanner.storage.postgres.chat_repository import PostgresChatRepository
from sportscanner.storage.postgres.database import engine

from sportscanner.agents.evals.judge import judge_agent_response

from .schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentChatSessionCreateRequest,
    AgentChatSessionDetail,
    AgentChatSessionMessage,
    AgentChatSessionSummary,
    AgentEvalRequest,
    AgentEvalResponse,
    AgentTrajectorySchema,
    JudgeScoresSchema,
    ToolCallRecordSchema,
)

router = APIRouter()
_tracer = trace.get_tracer(__name__)
_MAX_CHAT_TRACE_TEXT_LENGTH = 512
_MAX_CHAT_IO_TRACE_LENGTH = 2048
_chat_repository = PostgresChatRepository(engine)


def _coerce_ui_blocks(value: Any) -> Optional[list[dict[str, Any]]]:
    if not isinstance(value, list):
        return None

    blocks: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            blocks.append(item)
    return blocks or None


def _resolve_kinde_user_id(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    try:
        access_token = get_kinde_access_token(refresh_token=authorization)
        user_details = get_kinde_user_details(access_token)
        return user_details.get("id")
    except HTTPException:
        raise
    except Exception as exc:
        logging.warning(
            "Unable to resolve Kinde user id for chat persistence: "
            f"{type(exc).__name__}: {exc}"
        )
        return None


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _require_kinde_user_id(authorization: Optional[str]) -> str:
    user_id = _resolve_kinde_user_id(authorization)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization token is required for chat session history.",
        )
    return user_id


@router.get(
    "/sessions",
    response_model=list[AgentChatSessionSummary],
    status_code=status.HTTP_200_OK,
)
async def list_chat_sessions(
    Authorization: str = Header(
        default=None,
        title="Kinde refresh token used to scope chat sessions per user.",
    ),
    limit: int = Query(default=20, ge=1, le=100),
):
    """
    List persisted chat sessions for the authenticated user.
    """
    user_id = _require_kinde_user_id(Authorization)
    rows = _chat_repository.list_sessions(kinde_user_id=user_id, limit=limit)
    return [AgentChatSessionSummary(**row) for row in rows]


@router.post(
    "/sessions",
    response_model=AgentChatSessionDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat_session(
    body: AgentChatSessionCreateRequest,
    Authorization: str = Header(
        default=None,
        title="Kinde refresh token used to scope chat sessions per user.",
    ),
):
    """
    Create a new persisted chat session for the authenticated user.
    """
    user_id = _require_kinde_user_id(Authorization)
    created = _chat_repository.create_session(kinde_user_id=user_id, title=body.title)
    return AgentChatSessionDetail(
        id=created.id,
        title=created.title,
        created_at=created.created_at,
        updated_at=created.updated_at,
        messages=[],
    )


@router.get(
    "/sessions/{chat_session_id}",
    response_model=AgentChatSessionDetail,
    status_code=status.HTTP_200_OK,
)
async def get_chat_session(
    chat_session_id: str,
    Authorization: str = Header(
        default=None,
        title="Kinde refresh token used to scope chat sessions per user.",
    ),
):
    """
    Retrieve a persisted chat session and its messages for the authenticated user.
    """
    user_id = _require_kinde_user_id(Authorization)
    session_row, messages = _chat_repository.get_session_with_messages(
        kinde_user_id=user_id,
        chat_session_id=chat_session_id,
    )
    if not session_row:
        raise HTTPException(status_code=404, detail="Chat session not found.")

    return AgentChatSessionDetail(
        id=session_row.id,
        title=session_row.title,
        created_at=session_row.created_at,
        updated_at=session_row.updated_at,
        messages=[
            AgentChatSessionMessage(
                id=message.id,
                role=message.role,
                content=message.content,
                follow_up_questions=getattr(message, "follow_up_questions", None),
                used_tools=message.used_tools,
                model=message.model,
                ui_blocks=_coerce_ui_blocks(message.ui_blocks),
                created_at=message.created_at,
            )
            for message in messages
        ],
    )


@router.post("/agent", response_model=AgentChatResponse, status_code=status.HTTP_200_OK)
async def chat_with_sportscanner_agent(
    body: AgentChatRequest,
    Authorization: str = Header(
        default=None,
        title=(
            "Optional Kinde refresh token (usually sent as 'Bearer <token>') to "
            "enable profile-aware responses such as postcode-based 'near me' queries."
        ),
    ),
):
    """
    Conversational endpoint powered by a Google ADK agent + SportScanner MCP tools.

    The agent can answer questions about venue proximity, court availability,
    and postcode/venue exploration by selecting and invoking MCP tools.
    """
    with _tracer.start_as_current_span("sportscanner.chat.agent.request") as span:
        if _OI_SPAN_KIND_KEY and _OI_AGENT_SPAN_KIND:
            span.set_attribute(_OI_SPAN_KIND_KEY, _OI_AGENT_SPAN_KIND)
        span.set_attribute("sportscanner.chat.message_count", len(body.messages))
        span.set_attribute("sportscanner.chat.has_authorization", bool(Authorization))
        if _OI_SESSION_ID_KEY and body.chat_session_id:
            span.set_attribute(_OI_SESSION_ID_KEY, body.chat_session_id)
        latest_user_message = next(
            (msg.content for msg in reversed(body.messages) if msg.role == "user"),
            "",
        )
        if latest_user_message:
            span.set_attribute(
                "sportscanner.chat.latest_user_message",
                latest_user_message[:_MAX_CHAT_TRACE_TEXT_LENGTH],
            )
            if _OI_INPUT_VALUE_KEY:
                span.set_attribute(
                    _OI_INPUT_VALUE_KEY,
                    latest_user_message[:_MAX_CHAT_IO_TRACE_LENGTH],
                )
        try:
            turns = [AgentTurn(role=msg.role, content=msg.content) for msg in body.messages]
            result = await sportscanner_chat_agent.chat(
                turns=turns,
                authorization=Authorization,
                session_id=body.chat_session_id,
            )
            span.set_attribute("sportscanner.chat.used_tools_count", len(result.used_tools))
            if result.used_tools:
                span.set_attribute(
                    "sportscanner.chat.used_tools",
                    ", ".join(result.used_tools[:20]),
                )
            span.set_attribute("sportscanner.chat.model", result.model)
            ui_blocks = _coerce_ui_blocks(result.ui_blocks)
            if ui_blocks:
                span.set_attribute("sportscanner.chat.ui_blocks_count", len(ui_blocks))
            persisted_chat_session_id = None
            if Authorization and latest_user_message:
                try:
                    kinde_user_id = _resolve_kinde_user_id(Authorization)
                    if kinde_user_id:
                        persisted_chat_session_id = _chat_repository.append_chat_exchange(
                            kinde_user_id=kinde_user_id,
                            chat_session_id=body.chat_session_id,
                            user_message=latest_user_message,
                            assistant_message=result.reply,
                            used_tools=result.used_tools,
                            model=result.model,
                            ui_blocks=ui_blocks,
                        )
                        span.set_attribute(
                            "sportscanner.chat.persisted_session_id",
                            persisted_chat_session_id,
                        )
                except Exception as exc:
                    span.set_attribute(
                        "sportscanner.chat.persistence_error",
                        f"{type(exc).__name__}",
                    )
                    logging.warning(
                        "Failed to persist chat exchange: "
                        f"{type(exc).__name__}: {exc}"
                    )
            return AgentChatResponse(
                reply=result.reply,
                used_tools=result.used_tools,
                model=result.model,
                follow_up_questions=result.follow_up_questions,
                ui_blocks=ui_blocks,
                chat_session_id=persisted_chat_session_id or body.chat_session_id,
            )
        except ValueError as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(
                Status(
                    StatusCode.ERROR,
                    "SportScanner agent is temporarily unavailable.",
                )
            )
            logging.error("Unhandled error in /chat/agent: " f"{type(exc).__name__}: {exc}")
            raise HTTPException(
                status_code=500,
                detail="SportScanner agent is temporarily unavailable.",
            )
        finally:
            # `result` may be unavailable on errors, so use guarded lookup.
            if _OI_OUTPUT_VALUE_KEY:
                try:
                    if "result" in locals() and getattr(result, "reply", None):
                        span.set_attribute(
                            _OI_OUTPUT_VALUE_KEY,
                            str(result.reply)[:_MAX_CHAT_IO_TRACE_LENGTH],
                        )
                except Exception:
                    pass


@router.post(
    "/agent/stream",
    status_code=status.HTTP_200_OK,
)
async def stream_chat_with_sportscanner_agent(
    body: AgentChatRequest,
    Authorization: str = Header(
        default=None,
        title=(
            "Optional Kinde refresh token (usually sent as 'Bearer <token>') to "
            "enable profile-aware responses such as postcode-based 'near me' queries."
        ),
    ),
):
    """
    Streaming chat endpoint backed by the same ADK + MCP toolchain.

    Response format is SSE (`text/event-stream`) with events:
    - `start`: includes the provisional chat session id
    - `delta`: incremental markdown text chunks
    - `replace`: full markdown replacement when the sanitized output changes shape
    - `meta`: model/tool metadata
    - `done`: final payload with full reply and metadata
    - `error`: recoverable error payload
    """

    latest_user_message = next(
        (msg.content for msg in reversed(body.messages) if msg.role == "user"),
        "",
    )

    async def event_stream() -> AsyncIterator[str]:
        final_reply = ""
        with _tracer.start_as_current_span("sportscanner.chat.agent.stream.invocation") as inner_span:
            if _OI_SPAN_KIND_KEY and _OI_AGENT_SPAN_KIND:
                inner_span.set_attribute(_OI_SPAN_KIND_KEY, _OI_AGENT_SPAN_KIND)
            inner_span.set_attribute("sportscanner.chat.message_count", len(body.messages))
            inner_span.set_attribute("sportscanner.chat.has_authorization", bool(Authorization))
            if _OI_SESSION_ID_KEY and body.chat_session_id:
                inner_span.set_attribute(_OI_SESSION_ID_KEY, body.chat_session_id)
            if latest_user_message:
                inner_span.set_attribute(
                    "sportscanner.chat.latest_user_message",
                    latest_user_message[:_MAX_CHAT_TRACE_TEXT_LENGTH],
                )
                if _OI_INPUT_VALUE_KEY:
                    inner_span.set_attribute(
                        _OI_INPUT_VALUE_KEY,
                        latest_user_message[:_MAX_CHAT_IO_TRACE_LENGTH],
                    )

            try:
                turns = [AgentTurn(role=msg.role, content=msg.content) for msg in body.messages]
                streamed_tools: list[str] = []
                streamed_model = ""
                agent_session_id = ""
                streamed_follow_up_questions: list[str] = []

                async for update in sportscanner_chat_agent.stream_chat(
                    turns=turns,
                    authorization=Authorization,
                    session_id=body.chat_session_id,
                ):
                    if update.event == "start":
                        agent_session_id = update.agent_session_id or agent_session_id
                        yield _sse_event(
                            "start",
                            {
                                "chat_session_id": body.chat_session_id,
                                "agent_session_id": agent_session_id,
                            },
                        )
                        continue
                    if update.event == "tool_start":
                        if update.delta:
                            yield _sse_event("tool_start", {"tool": update.delta})
                        continue
                    if update.event == "delta":
                        if update.delta:
                            final_reply += update.delta
                            yield _sse_event("delta", {"delta": update.delta})
                        continue
                    if update.event == "replace":
                        final_reply = update.content
                        yield _sse_event("replace", {"content": final_reply})
                        continue
                    if update.event == "done":
                        final_reply = update.reply or final_reply
                        streamed_tools = update.used_tools
                        streamed_model = update.model
                        agent_session_id = update.agent_session_id or agent_session_id
                        streamed_follow_up_questions = update.follow_up_questions

                if not final_reply:
                    raise ValueError("Agent did not produce a readable assistant response.")

                inner_span.set_attribute("sportscanner.chat.used_tools_count", len(streamed_tools))
                if streamed_tools:
                    inner_span.set_attribute(
                        "sportscanner.chat.used_tools",
                        ", ".join(streamed_tools[:20]),
                    )
                if streamed_model:
                    inner_span.set_attribute("sportscanner.chat.model", streamed_model)

                persisted_chat_session_id = body.chat_session_id
                if Authorization and latest_user_message:
                    try:
                        kinde_user_id = _resolve_kinde_user_id(Authorization)
                        if kinde_user_id:
                            persisted_chat_session_id = _chat_repository.append_chat_exchange(
                                kinde_user_id=kinde_user_id,
                                chat_session_id=body.chat_session_id,
                                user_message=latest_user_message,
                                assistant_message=final_reply,
                                used_tools=streamed_tools,
                                model=streamed_model,
                                ui_blocks=None,
                            )
                            inner_span.set_attribute(
                                "sportscanner.chat.persisted_session_id",
                                persisted_chat_session_id,
                            )
                    except Exception as exc:
                        inner_span.set_attribute(
                            "sportscanner.chat.persistence_error",
                            f"{type(exc).__name__}",
                        )
                        logging.warning(
                            "Failed to persist streamed chat exchange: "
                            f"{type(exc).__name__}: {exc}"
                        )

                yield _sse_event(
                    "meta",
                    {
                        "used_tools": streamed_tools,
                        "model": streamed_model,
                        "follow_up_questions": streamed_follow_up_questions,
                        "chat_session_id": persisted_chat_session_id or body.chat_session_id,
                        "agent_session_id": agent_session_id,
                    },
                )
                yield _sse_event(
                    "done",
                    {
                        "reply": final_reply,
                        "used_tools": streamed_tools,
                        "model": streamed_model,
                        "follow_up_questions": streamed_follow_up_questions,
                        "chat_session_id": persisted_chat_session_id or body.chat_session_id,
                        "agent_session_id": agent_session_id,
                    },
                )
            except ValueError as exc:
                inner_span.record_exception(exc)
                inner_span.set_status(Status(StatusCode.ERROR, str(exc)))
                yield _sse_event("error", {"error": str(exc), "status_code": 400})
            except Exception as exc:
                inner_span.record_exception(exc)
                inner_span.set_status(
                    Status(
                        StatusCode.ERROR,
                        "SportScanner agent is temporarily unavailable.",
                    )
                )
                logging.error(
                    "Unhandled error in /chat/agent/stream: "
                    f"{type(exc).__name__}: {exc}"
                )
                yield _sse_event(
                    "error",
                    {
                        "error": "SportScanner agent is temporarily unavailable.",
                        "status_code": 500,
                    },
                )
            finally:
                if _OI_OUTPUT_VALUE_KEY and final_reply:
                    inner_span.set_attribute(
                        _OI_OUTPUT_VALUE_KEY,
                        final_reply[:_MAX_CHAT_IO_TRACE_LENGTH],
                    )

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=headers,
    )


@router.post(
    "/agent/eval",
    response_model=AgentEvalResponse,
    status_code=status.HTTP_200_OK,
)
async def eval_chat_with_sportscanner_agent(
    body: AgentEvalRequest,
    Authorization: str = Header(
        default=None,
        title="Optional Kinde refresh token for profile-aware agent responses.",
    ),
) -> AgentEvalResponse:
    """
    Run the SportScanner agent on a single query, capture the full tool
    trajectory, and score the response with an LLM-as-judge.

    Useful for evaluating agent quality, debugging tool-call chains, and
    demonstrating the impact of guardrails.
    """
    try:
        turns = [AgentTurn(role="user", content=body.query)]
        result = await sportscanner_chat_agent.chat(
            turns=turns,
            authorization=Authorization,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Agent failed: {exc}",
        )

    traj = result.trajectory
    if traj is None:
        from sportscanner.agents.evals.trajectory import AgentTrajectory
        traj = AgentTrajectory(query=body.query, final_reply=result.reply)

    judge_scores = await judge_agent_response(
        query=body.query,
        trajectory=traj,
        final_response=result.reply,
        judge_model=body.judge_model,
    )

    traj_schema = AgentTrajectorySchema(
        query=traj.query,
        tool_calls=[
            ToolCallRecordSchema(
                tool=tc.tool,
                input=tc.input,
                output=tc.output,
                timestamp_utc=tc.timestamp_utc,
                duration_ms=tc.duration_ms,
                guardrail_fired=tc.guardrail_fired,
                guardrail_original_input=tc.guardrail_original_input,
                error=tc.error,
            )
            for tc in traj.tool_calls
        ],
        final_reply=traj.final_reply,
        started_at=traj.started_at,
        completed_at=traj.completed_at,
        total_duration_ms=traj.total_duration_ms,
    )

    return AgentEvalResponse(
        query=body.query,
        reply=result.reply,
        used_tools=result.used_tools,
        trajectory=traj_schema,
        judge=JudgeScoresSchema(**{k: v for k, v in judge_scores.items() if k in JudgeScoresSchema.model_fields}),
        model=result.model,
    )
