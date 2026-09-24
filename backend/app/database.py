"""SQLite database access (T03 / FR01, FR05).

A single SQLAlchemy engine serves application records (users, roles, and —
from Day 2 on — document records and conversation history). Tables are
created on startup (see ``backend.app.main``); migrations are out of scope
for this sprint.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    # SQLite needs this flag because FastAPI serves requests on threads.
    connect_args={
        "check_same_thread": False,
        # Wait instead of failing with "database is locked" when another
        # request holds the write lock (chat persistence + admin upload).
        "timeout": 30,
    } if _settings.database_url.startswith("sqlite") else {},
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (idempotent)."""
    import backend.app.models  # noqa: F401  (registers models on Base)

    Base.metadata.create_all(bind=engine)