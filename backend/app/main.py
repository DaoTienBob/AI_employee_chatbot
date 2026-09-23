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
from backend.app.logging_config import setup_logging
from backend.app.models import Document, ROLES
from backend.app.routers import auth, documents
from backend.app.routers import chat, conversations
from backend.app.seed import seed_demo_users
from backend.app.vector_store import get_vector_store

settings = get_settings()

logger = logging.getLogger(__name__)


def _check_index_permissions(db) -> None:
    """Warn when ChromaDB chunk permissions drift from SQLite (RBAC).

    A crash between the SQL commit and an index restore could leave stale
    allow_* flags in the vector store. Retrieval still uses the chunk metadata,
    so drift must be detected and repaired by re-uploading the document.
    """
    if not settings.verify_index_on_startup:
        return
    try:
        store = get_vector_store()
    except Exception:
        logger.warning("Index permission check skipped: vector store unavailable")
        return
    documents_ = db.scalars(
        select(Document).where(Document.is_active.is_(True))
    ).all()
    for document in documents_:
        doc_key = f"DOC_{document.id:03d}"
        chunks = store._collection.get(  # noqa: SLF001 — internal health check
            where={"document_id": {"$eq": doc_key}}, include=["metadatas"], limit=5
        )
        for meta in chunks.get("metadatas") or []:
            for role in ROLES:
                indexed = bool(meta.get(f"allow_{role}"))
                recorded = getattr(document, f"allowed_{role}")
                if indexed != recorded:
                    logger.error(
                        "RBAC drift for %s (%s): SQLite grants %s=%s but "
                        "indexed chunk %s has %s. Re-upload this document "
                        "to repair index permissions.",
                        doc_key, document.document_name, role, recorded,
                        meta.get("chunk_id", "?"), indexed,
                    )
                    break


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Configure file logging, create SQLite tables and seed demo users."""
    setup_logging()
    init_db()
    with SessionLocal() as db:
        seed_demo_users(db)
        try:
            _check_index_permissions(db)
        except Exception:
            logger.exception("Startup index permission check failed")
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

