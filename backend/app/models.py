"""ORM models (T03). SQLite stores users and roles; from Day 2 on it also
holds document records and conversation history (FR02/FR05)."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
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