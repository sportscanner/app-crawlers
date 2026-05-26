from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import SQLModel, Session, select

from sportscanner.storage.postgres.tables import ChatMessage, ChatSession


def ensure_chat_tables(engine) -> None:
    """Create chat tables if they do not exist."""
    SQLModel.metadata.create_all(
        bind=engine,
        tables=[
            ChatSession.__table__,
            ChatMessage.__table__,
        ],
    )


def _preview_text(value: str, max_length: int = 140) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[: max_length - 1]}…"


class PostgresChatRepository:
    def __init__(self, engine):
        self.engine = engine

    def create_session(self, *, kinde_user_id: str, title: Optional[str] = None) -> ChatSession:
        with Session(self.engine) as session:
            row = ChatSession(
                kinde_user_id=kinde_user_id,
                title=title.strip() if title and title.strip() else None,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def list_sessions(self, *, kinde_user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        with Session(self.engine) as session:
            sessions = session.exec(
                select(ChatSession)
                .where(ChatSession.kinde_user_id == kinde_user_id)
                .order_by(ChatSession.updated_at.desc())
                .limit(limit)
            ).all()

            if not sessions:
                return []

            session_ids = [row.id for row in sessions]
            messages = session.exec(
                select(ChatMessage)
                .where(ChatMessage.chat_session_id.in_(session_ids))
                .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            ).all()

            stats_by_session: Dict[str, Dict[str, Any]] = {
                row.id: {"message_count": 0, "last_message_preview": None}
                for row in sessions
            }
            for message in messages:
                stats = stats_by_session.get(message.chat_session_id)
                if not stats:
                    continue
                stats["message_count"] += 1
                if not stats["last_message_preview"] and message.content:
                    stats["last_message_preview"] = _preview_text(message.content)

            return [
                {
                    "id": row.id,
                    "title": row.title,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                    "message_count": stats_by_session[row.id]["message_count"],
                    "last_message_preview": stats_by_session[row.id]["last_message_preview"],
                }
                for row in sessions
            ]

    def get_session_with_messages(
        self, *, kinde_user_id: str, chat_session_id: str
    ) -> Tuple[Optional[ChatSession], List[ChatMessage]]:
        with Session(self.engine) as session:
            chat_session = session.get(ChatSession, chat_session_id)
            if not chat_session or chat_session.kinde_user_id != kinde_user_id:
                return None, []

            messages = session.exec(
                select(ChatMessage)
                .where(ChatMessage.chat_session_id == chat_session_id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            ).all()
            return chat_session, messages

    def append_chat_exchange(
        self,
        *,
        kinde_user_id: str,
        user_message: str,
        assistant_message: str,
        used_tools: Optional[List[str]] = None,
        model: Optional[str] = None,
        ui_blocks: Optional[Any] = None,
        chat_session_id: Optional[str] = None,
    ) -> str:
        with Session(self.engine) as session:
            chat_session: Optional[ChatSession] = None
            if chat_session_id:
                chat_session = session.get(ChatSession, chat_session_id)
                if chat_session and chat_session.kinde_user_id != kinde_user_id:
                    chat_session = None

            if not chat_session:
                title = user_message.strip()[:80] if user_message.strip() else None
                chat_session = ChatSession(
                    kinde_user_id=kinde_user_id,
                    title=title,
                )
                session.add(chat_session)
                session.flush()

            now = datetime.utcnow()
            chat_session.updated_at = now
            if not chat_session.title and user_message.strip():
                chat_session.title = user_message.strip()[:80]

            session.add(
                ChatMessage(
                    chat_session_id=chat_session.id,
                    role="user",
                    content=user_message,
                    used_tools=[],
                    model=None,
                    ui_blocks=None,
                    created_at=now,
                )
            )
            session.add(
                ChatMessage(
                    chat_session_id=chat_session.id,
                    role="assistant",
                    content=assistant_message,
                    used_tools=used_tools or [],
                    model=model,
                    ui_blocks=ui_blocks,
                    created_at=now,
                )
            )

            session.commit()
            return chat_session.id
