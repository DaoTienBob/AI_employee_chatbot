"""Conversation history endpoints (T16/T18 / FR05).

GET /conversations      — list the current user's conversations.
GET /conversations/{id} — read messages only when owned by the requester.

Ownership is the only access control: a user cannot retrieve another user's
conversation, even by guessing its integer ID (T18).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import Conversation, Message, User
from backend.app.schemas import ConversationPublic, MessagePublic
from backend.app.security import get_current_user

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationPublic])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConversationPublic]:
    """List all conversations belonging to the current user (T18).

    Conversations are ordered newest-first so the UI can display recent history
    at the top.
    """
    convs = db.scalars(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.id.desc())
    ).all()
    return [
        ConversationPublic(id=c.id, created_at=c.created_at.isoformat()) for c in convs
    ]


@router.get("/{conversation_id}", response_model=list[MessagePublic])
def get_conversation_messages(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MessagePublic]:
    """Return all messages in a conversation, only if owned by the requester (T18).

    Returns 404 (not 403) for both missing and foreign conversations to avoid
    leaking the existence of other users' conversations.
    """
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    messages = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id)
    ).all()

    return [
        MessagePublic(
            id=m.id,
            role=m.role,
            content=m.content,
            created_at=m.created_at.isoformat(),
        )
        for m in messages
    ]

