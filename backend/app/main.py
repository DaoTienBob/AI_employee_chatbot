"""FastAPI application entry point (T01: initialize project and FastAPI backend;
T03: authentication and roles served via the auth router).

Run from the project root with:

    .venv/bin/uvicorn backend.app.main:app --reload --port 8000

Completion checks:
- T01: the API starts and ``/health`` returns success.
- T03: ``/auth/login`` issues a session; ``/auth/me`` identifies the role.
"""

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import get_settings
from backend.app.database import SessionLocal, init_db
from backend.app.logging_config import setup_logging
from backend.app.routers import auth, documents
from backend.app.routers import chat, conversations
from backend.app.seed import seed_demo_users

settings = get_settings()


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Configure file logging, create SQLite tables and seed demo users."""
    setup_logging()
    init_db()
    with SessionLocal() as db:
        seed_demo_users(db)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Role-aware RAG chatbot API. Authentication, document ingestion, "
        "role-filtered retrieval and grounded answers with source references."
    ),
    lifespan=lifespan,
    debug=settings.debug,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(conversations.router)


@app.get("/health", tags=["system"])
def health() -> dict:
    """Liveness probe (T01 completion check)."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "debug": settings.debug,
    }


@app.get("/", tags=["system"])
def root() -> dict:
    """Basic service banner."""
    return {
        "message": f"{settings.app_name} API is running",
        "docs": "/docs",
        "health": "/health",
        "debug": settings.debug,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True, log_level="debug")

