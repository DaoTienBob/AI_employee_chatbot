"""Request/response schemas for the API (T03/T04)."""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.models import ROLES

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(BaseModel):
    """Credentials submitted to /auth/login."""

    email: str = Field(..., description="Employee email address")
    password: str = Field(..., min_length=1, description="Plaintext password")

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_PATTERN.match(value):
            raise ValueError("must be a valid email address")
        return value

    @field_validator("password")
    @classmethod
    def _check_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password must be at most 72 bytes (bcrypt limit)")
        return value


class UserPublic(BaseModel):
    """User fields safe to expose to the client (never the password hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: str
    is_admin: bool


class TokenResponse(BaseModel):
    """Bearer token issued by /auth/login."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the token expires
    user: UserPublic


class DocumentPublic(BaseModel):
    """Document record safe to expose (no file path, no raw content)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_name: str
    file_type: str
    file_size: int
    allowed_roles: list[str]
    uploaded_at: str  # ISO timestamp; str keeps the schema JSON-friendly


class DocumentUploadResponse(BaseModel):
    """Result of a successful /documents/upload (T04)."""

    document: DocumentPublic
    chunk_count: int
    sections: list[str]  # section titles detected during extraction


class DocumentReplaceResponse(BaseModel):
    """Result of a successful PUT /documents/{id} replacement (T11/FR08)."""

    document: DocumentPublic
    chunk_count: int
    sections: list[str]


# ---------------------------------------------------------------------------
# Phase 3 — Chat / RAG schemas (T13-T18)
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Body for POST /chat (T14)."""

    question: str = Field(..., min_length=1, max_length=2000, description="Employee question")
    conversation_id: int | None = Field(
        None, description="Continue an existing conversation; omit to start a new one"
    )

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value


class SourceReference(BaseModel):
    """A single cited document section returned with a RAG answer (T15/FR06)."""

    document_name: str
    section: str
    chunk_id: str


class ChatResponse(BaseModel):
    """Response from POST /chat (T14/T15)."""

    answer: str
    sources: list[SourceReference]
    conversation_id: int
    fallback: bool = False  # True when no authorized evidence was found (T17)


class ConversationPublic(BaseModel):
    """Conversation summary for GET /conversations (T18)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: str  # ISO timestamp


class MessagePublic(BaseModel):
    """A single message for GET /conversations/{id} (T18)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: str  # ISO timestamp