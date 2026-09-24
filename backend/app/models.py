"""ORM models (T03/T04). SQLite stores users, roles and document records; from
Day 4 on it also holds conversation history (FR05).

Schema follows roadmap §8 (Basic Database Design).
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base

# Employee-facing roles (roadmap §3.4 minimal RBAC). Administrator permission
# is a separate flag (User.is_admin), not a fourth employee role.
ROLES = ("employee", "hr", "manager")


def utc_now() -> datetime:
    """Timezone-aware UTC timestamp for defaults."""
    return datetime.now(timezone.utc)


class User(Base):
    """An employee account. ``role`` drives document access (FR03);
    ``is_admin`` grants document upload/replace rights (FR02/FR08)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="employee")
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User id={self.id} email={self.email!r} role={self.role!r}>"


class Document(Base):
    """An ingested document record (roadmap §8: document_id, document_name,
    file_path, allowed_roles, uploaded_at).

    ``allowed_*`` columns are scalar booleans mirroring the ChromaDB chunk
    metadata flags (allow_employee / allow_hr / allow_manager, §3.2) so SQLite
    and the vector store agree on permissions.
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)  # pdf | docx
    file_size: Mapped[int] = mapped_column(nullable=False)  # bytes
    allowed_employee: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allowed_hr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allowed_manager: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    def allowed_roles(self) -> list[str]:
        """Role names granted access, in canonical order."""
        flags = {
            "employee": self.allowed_employee,
            "hr": self.allowed_hr,
            "manager": self.allowed_manager,
        }
        return [role for role in ROLES if flags[role]]

    def visible_to(self, role: str) -> bool:
        """Whether this document grants access to ``role``.

        ``employee`` is the general role: a document tagged for employees is
        visible to every user (employee, hr and manager). A document is
        accessible to a role when it is employee-visible OR explicitly grants
        that role.
        """
        return bool(self.allowed_employee or getattr(self, f"allowed_{role}", False))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Document id={self.id} name={self.document_name!r} active={self.is_active}>"


# ---------------------------------------------------------------------------
# Conversation history (T16 / FR05, roadmap §8)
# ---------------------------------------------------------------------------


class Conversation(Base):
    """A chat session owned by one user.

    Ownership is enforced at the API layer (T18): a user may only read or
    continue conversations they created.
    """

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Conversation id={self.id} user_id={self.user_id}>"


class Message(Base):
    """A single message inside a conversation.

    ``role`` is ``"user"`` or ``"assistant"`` — matching the LLM message-list
    convention so history rows can be fed back into the LLM directly.
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Message id={self.id} conv={self.conversation_id} role={self.role!r}>"