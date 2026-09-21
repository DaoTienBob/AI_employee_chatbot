"""FastAPI application entry point (T01: Initialize project and FastAPI backend).

Run from the project root with:

    .venv/bin/uvicorn backend.app.main:app --reload --port 8000

Completion check for T01: the API starts and ``/health`` returns success.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Role-aware RAG chatbot API. Authentication, document ingestion, "
        "role-filtered retrieval and grounded answers with source references."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health() -> dict:
    """Liveness probe (T01 completion check)."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
    }


@app.get("/", tags=["system"])
def root() -> dict:
    """Basic service banner."""
    return {
        "message": f"{settings.app_name} API is running",
        "docs": "/docs",
        "health": "/health",
    }
