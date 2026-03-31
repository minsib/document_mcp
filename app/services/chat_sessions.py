"""
Chat session persistence helpers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from sqlalchemy.orm import Session

from app.models import database as db_models


SESSION_NAMESPACE = uuid5(NAMESPACE_URL, "document_mcp.chat_sessions")


def normalize_session_id(
    raw_session_id: Optional[str],
    *,
    user_id: str,
    doc_id: str,
) -> str:
    """Normalize a client-provided session ID to a stable UUID string."""
    if not raw_session_id:
        return str(uuid4())

    try:
        return str(UUID(raw_session_id))
    except ValueError:
        seed = f"{user_id}:{doc_id}:{raw_session_id}"
        return str(uuid5(SESSION_NAMESPACE, seed))


def ensure_chat_session(
    db: Session,
    *,
    session_id: str,
    user_id: str,
    doc_id: str,
    status: str = "active",
) -> db_models.ChatSession:
    """Create or validate a persisted chat session."""
    session_uuid = UUID(session_id)
    user_uuid = UUID(user_id)
    doc_uuid = UUID(doc_id)

    chat_session = db.query(db_models.ChatSession).filter(
        db_models.ChatSession.session_id == session_uuid
    ).first()

    if chat_session:
        if chat_session.user_id != user_uuid or chat_session.doc_id != doc_uuid:
            raise ValueError("session_id does not belong to the current user/document")
        chat_session.status = status
        chat_session.updated_at = datetime.now(timezone.utc)
        return chat_session

    chat_session = db_models.ChatSession(
        session_id=session_uuid,
        user_id=user_uuid,
        doc_id=doc_uuid,
        status=status,
    )
    db.add(chat_session)
    # Flush immediately so subsequent chat_messages inserts in the same request
    # can satisfy the foreign-key constraint reliably.
    db.flush()
    return chat_session


def append_chat_message(
    db: Session,
    *,
    session_id: str,
    role: str,
    content: str,
    meta: Optional[dict[str, Any]] = None,
) -> db_models.ChatMessage:
    """Append a message to a persisted chat session."""
    message = db_models.ChatMessage(
        session_id=UUID(session_id),
        role=role,
        content=content,
        meta=meta or {},
    )
    db.add(message)
    chat_session = db.query(db_models.ChatSession).filter(
        db_models.ChatSession.session_id == UUID(session_id)
    ).first()
    if chat_session:
        chat_session.updated_at = datetime.now(timezone.utc)
    return message
