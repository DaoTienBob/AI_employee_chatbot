"""FastAPI application entry point (T01: initialize project and FastAPI backend;
T03: authentication and roles served via the auth router).

Run from the project root with:

    .venv/bin/uvicorn backend.app.main:app --reload --port 8000

Completion checks:
- T01: the API starts and ``/health`` returns success.
- T03: ``/auth/login`` issues a session; ``/auth/me`` identifies the role.
"""

import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from backend.app.config import get_settings
from backend.app.database import SessionLocal, init_db
from backend.app.llm import unload_ollama_models
from backend.app.logging_config import setup_logging
from backend.app.models import Document, ROLES
from backend.app.routers import auth, documents
from backend.app.routers import chat, conversations
from backend.app.seed import seed_demo_users
from backend.app.vector_store import get_vector_store

settings = get_settings()

logger = logging.getLogger(__name__)


def _check_index_permissions(db) -> None:
    """Refuse startup when indexed chunk permissions drift from SQLite (RBAC).

    A crash between the SQL commit and an index restore could leave stale
    allow_* flags in the vector store. Retrieval still uses the chunk metadata,
    so drift must be detected and repaired by re-uploading the document.
    """
    if not settings.verify_index_on_startup:
        return
    store = get_vector_store()
    records = {f"DOC_{d.id:03d}": d for d in db.scalars(select(Document)).all()}
    offset = 0
    while True:
        batch = store._collection.get(include=["metadatas"], limit=500, offset=offset)
        metadata = batch.get("metadatas") or []
        for meta in metadata:
            document = records.get(meta.get("document_id"))
            if document is None or not document.is_active or any(
                meta.get(f"allow_{role}") != getattr(document, f"allowed_{role}")
                for role in ROLES
            ):
                raise RuntimeError("Index permission drift detected; repair the index before serving requests")
        if len(metadata) < 500:
            break
        offset += len(metadata)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Configure file logging, create SQLite tables, seed users; on shutdown
    evict every Ollama model this process loaded so its RAM/VRAM is freed."""
    setup_logging()
    init_db()
    with SessionLocal() as db:
        seed_demo_users(db)
        _check_index_permissions(db)
    yield
    if settings.unload_ollama_on_shutdown:
        unload_ollama_models()


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
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
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

