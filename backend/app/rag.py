"""RAG orchestration (T14/T15/T16/T17/T18 / FR04-FR07).

Core pipeline function ``answer_question`` runs the complete retrieval-augmented
generation flow for one user question:

1. Resolve or create a ``Conversation`` owned by this user.
2. Load recent safe history (T16) from that conversation.
3. Embed the question (+context) and retrieve authorized chunks (T10).
4. Fallback: if evidence is too weak, return a safe message (T17/FR07).
5. Build a grounding prompt with only authorized chunks.
6. Call the LLM (T13).
7. Persist both messages to SQLite (T16).
8. Return answer + source references derived from chunk metadata (T15/FR06).

Security invariants (roadmap §3.3):
- ``user.role`` always comes from the DB — never from the request body.
- Restricted chunks never enter the prompt (ChromaDB filter in VectorStore.search).
- History is restricted to the owning user (T18).
- Source references are derived from retrieved authorized chunk metadata only.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.llm import LLMError, get_llm_client
from backend.app.logging_config import setup_logging
from backend.app.models import Conversation, Message, ROLES
from backend.app.schemas import ChatResponse, SourceReference
from backend.app.vector_store import get_vector_store

if TYPE_CHECKING:
    from backend.app.models import User

# Ensure the RAG retrieval logs are written to the configured .log file even
# when `answer_question` is invoked directly (e.g. from tests / scripts).
setup_logging()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Maximum cosine *distance* to consider a chunk as useful evidence.
# Chroma uses cosine distance (0 = identical, 2 = opposite); 0.7 is a
# reasonable threshold for "probably relevant".  Raise to be more permissive,
# lower to be stricter.
FALLBACK_DISTANCE_THRESHOLD: float = 0.7

# How many recent messages to feed back to the LLM as conversation context.
HISTORY_WINDOW: int = 6  # 3 turns = 3 user + 3 assistant

# System prompt template — authorized chunks are inserted as {context}.
_SYSTEM_PROMPT = """\
You are the AI Employee Knowledge Assistant for an internal company knowledge base.
Answer the employee's question using ONLY the document excerpts provided below.
If the excerpts do not contain enough information to answer confidently, say so clearly
instead of guessing. Do not reveal restricted information beyond what is shown.
Be concise and helpful.

--- Authorized document excerpts ---
{context}
--- End of excerpts ---
"""

_FALLBACK_ANSWER = (
    "I'm sorry, I couldn't find sufficient information in your authorized documents "
    "to answer that question. Please contact HR or your manager for further assistance."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_or_create_conversation(
    user_id: int,
    conversation_id: int | None,
    db: Session,
) -> Conversation:
    """Return an existing conversation owned by ``user_id`` or create a new one.

    Raises ``PermissionError`` if the requested conversation exists but belongs
    to a different user (T18 ownership check).
    """
    if conversation_id is not None:
        conv = db.get(Conversation, conversation_id)
        if conv is None:
            # Treat a missing ID as starting a new conversation rather than
            # leaking the existence of another user's conversation.
            logger.warning(
                "Conversation %d not found; creating new one for user %d",
                conversation_id,
                user_id,
            )
            conv = None
        elif conv.user_id != user_id:
            # Hard security boundary — raise so the router returns 403.
            raise PermissionError(
                f"Conversation {conversation_id} is not owned by user {user_id}"
            )
    else:
        conv = None

    if conv is None:
        conv = Conversation(user_id=user_id)
        db.add(conv)
        db.flush()  # assign conv.id before inserting messages

    return conv


def _load_history(conversation_id: int, db: Session) -> list[dict]:
    """Return the last ``HISTORY_WINDOW`` messages as LLM-ready dicts.

    Only content from this conversation is loaded — no cross-user leakage.
    """
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(HISTORY_WINDOW)
    ).all()
    # Reverse to chronological order for the prompt.
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


def _build_retrieval_query(question: str, history: list[dict]) -> str:
    """Combine the current question with safe recent context for better retrieval.

    Only the last *user* message (if any) is appended to avoid the query
    growing unbounded or accidentally embedding assistant content that might
    contain sensitive source text.
    """
    last_user = next(
        (m["content"] for m in reversed(history) if m["role"] == "user"), ""
    )
    if last_user and last_user != question:
        return f"{last_user}\n{question}"
    return question


def _build_sources(hits: list[dict]) -> list[SourceReference]:
    """Derive source references from retrieved chunk metadata (T15/FR06).

    Only chunks that passed the role filter are present in *hits*, so every
    returned reference corresponds to an authorized chunk (security invariant).
    """
    seen: set[str] = set()
    sources: list[SourceReference] = []
    for hit in hits:
        meta = hit.get("metadata") or {}
        chunk_id = hit.get("chunk_id", "")
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        sources.append(
            SourceReference(
                document_name=meta.get("document_name", "Unknown document"),
                section=meta.get("section", ""),
                chunk_id=chunk_id,
            )
        )
    return sources


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def answer_question(
    question: str,
    user: "User",
    db: Session,
    conversation_id: int | None = None,
) -> ChatResponse:
    """Full RAG pipeline: retrieve → (fallback or ground) → generate → persist.

    Parameters
    ----------
    question:
        The employee's current question (already validated by the router).
    user:
        The authenticated user; ``user.role`` determines retrieval permissions.
    db:
        SQLAlchemy session for history persistence.
    conversation_id:
        Optional ID of an existing conversation owned by this user.
        Pass ``None`` to start a fresh conversation.

    Returns
    -------
    ChatResponse
        Contains the answer, source references, conversation ID, and a
        ``fallback`` flag indicating whether authorized evidence was found.
    """
    # ------------------------------------------------------------------
    # 0. Validate role
    # ------------------------------------------------------------------
    if user.role not in ROLES:
        logger.error("User %d has unknown role %r; refusing to answer", user.id, user.role)
        raise ValueError(f"Unknown role: {user.role!r}")

    # ------------------------------------------------------------------
    # 1. Resolve or create conversation (T16/T18)
    # ------------------------------------------------------------------
    conv = _get_or_create_conversation(user.id, conversation_id, db)

    # ------------------------------------------------------------------
    # 2. Load safe history (T16)
    # ------------------------------------------------------------------
    history = _load_history(conv.id, db)

    # ------------------------------------------------------------------
    # 3. Embed + retrieve authorized chunks (T10)
    # ------------------------------------------------------------------
    retrieval_query = _build_retrieval_query(question, history)
    settings = get_settings()
    logger.info(
        "RAG retrieval start | user=%d role=%s top_k=%d query=%r",
        user.id,
        user.role,
        settings.retrieval_top_k,
        retrieval_query,
    )
    hits = get_vector_store().search(
        retrieval_query,
        user.role,
        top_k=settings.retrieval_top_k,
    )
    logger.info(
        "RAG retrieval done | user=%d role=%s raw_hits=%d",
        user.id,
        user.role,
        len(hits),
    )
    for hit in hits:
        meta = hit.get("metadata") or {}
        logger.info(
            "RAG hit | chunk=%s doc=%r section=%r distance=%s",
            hit.get("chunk_id"),
            meta.get("document_name", "?"),
            meta.get("section", ""),
            hit.get("distance"),
        )

    # ------------------------------------------------------------------
    # 4. Fallback check (T17/FR07)
    # ------------------------------------------------------------------
    useful_hits = [
        h for h in hits
        if h.get("distance") is None or h["distance"] <= FALLBACK_DISTANCE_THRESHOLD
    ]
    logger.info(
        "RAG evidence | user=%d usable=%d threshold=%s",
        user.id,
        len(useful_hits),
        FALLBACK_DISTANCE_THRESHOLD,
    )

    if not useful_hits:
        logger.info(
            "No authorized evidence for user=%d role=%s; returning fallback",
            user.id,
            user.role,
        )
        # Persist the exchange even on fallback so history is complete.
        _persist_messages(conv.id, question, _FALLBACK_ANSWER, db)
        return ChatResponse(
            answer=_FALLBACK_ANSWER,
            sources=[],
            conversation_id=conv.id,
            fallback=True,
        )

    # ------------------------------------------------------------------
    # 5. Build grounding prompt (T14)
    # ------------------------------------------------------------------
    context_blocks: list[str] = []
    for hit in useful_hits:
        meta = hit.get("metadata") or {}
        doc_name = meta.get("document_name", "Document")
        section = meta.get("section", "")
        header = f"[{doc_name}" + (f" — {section}" if section else "") + "]"
        context_blocks.append(f"{header}\n{hit['text']}")
    context = "\n\n".join(context_blocks)

    system_message = {"role": "system", "content": _SYSTEM_PROMPT.format(context=context)}
    messages: list[dict] = [system_message, *history, {"role": "user", "content": question}]

    # ------------------------------------------------------------------
    # 6. Call LLM (T13)
    # ------------------------------------------------------------------
    try:
        llm = get_llm_client()
        answer = llm.complete(messages)
    except LLMError as exc:
        logger.error("LLM call failed: %s", exc)
        # Return a safe error answer; do NOT expose LLM internals.
        fallback_answer = (
            "I'm currently unable to generate an answer. "
            "Please try again in a moment."
        )
        _persist_messages(conv.id, question, fallback_answer, db)
        return ChatResponse(
            answer=fallback_answer,
            sources=[],
            conversation_id=conv.id,
            fallback=True,
        )

    # ------------------------------------------------------------------
    # 7. Persist both messages (T16)
    # ------------------------------------------------------------------
    _persist_messages(conv.id, question, answer, db)

    # ------------------------------------------------------------------
    # 8. Build source references (T15)
    # ------------------------------------------------------------------
    sources = _build_sources(useful_hits)

    return ChatResponse(
        answer=answer,
        sources=sources,
        conversation_id=conv.id,
        fallback=False,
    )


def _persist_messages(
    conversation_id: int, question: str, answer: str, db: Session
) -> None:
    """Write the user question and assistant answer to the messages table."""
    db.add(Message(conversation_id=conversation_id, role="user", content=question))
    db.add(Message(conversation_id=conversation_id, role="assistant", content=answer))
    db.commit()

