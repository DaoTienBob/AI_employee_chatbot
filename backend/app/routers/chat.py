"""Chat endpoint (T14/T16/T17/T18 / FR04-FR07).

POST /chat — authenticated, role-aware RAG answer generation.

The role is always read from the authenticated session (``get_current_user``
reloads from SQLite on every request); the request body may NOT override it.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import User
from backend.app.rag import answer_question
from backend.app.schemas import ChatRequest, ChatResponse
from backend.app.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatResponse:
    """Role-aware RAG answer; authenticated employees only (FR04/T14).

    The ``conversation_id`` field is optional:
    - Omit it to start a new conversation.
    - Supply the ID returned by a previous call to continue a conversation.

    The role is derived entirely from the authenticated session; any
    ``role`` field in the request body is ignored (roadmap security invariant).
    """
    try:
        return answer_question(
            question=payload.question,
            user=current_user,
            db=db,
            conversation_id=payload.conversation_id,
        )
    except PermissionError as exc:
        # Conversation belongs to a different user (T18).
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conversation not found or access denied",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Unhandled error in /chat for user %d", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI service is temporarily unavailable. Please try again shortly.",
        ) from exc

