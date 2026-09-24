"""Application configuration (T01: environment configuration).

Values load from the project-root ``.env`` file when present; every field has a
sane default so the app runs out of the box for local development.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> project root is three levels up
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

# MIME types accepted for ingestion (FR02)
SUPPORTED_FILE_EXTENSIONS = (".pdf", ".docx")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "AI Employee Knowledge Assistant"
    app_version: str = "0.1.0"
    debug: bool = Field(
        default=True,
        validation_alias=AliasChoices("debug", "app_debug", "DEBUG", "APP_DEBUG"),
    )

    # --- Sessions / security (FR01) ---
    secret_key: str = "dev-only-change-me"
    access_token_expire_minutes: int = 60

    # --- Storage ---
    database_url: str = f"sqlite:///{DATA_DIR / 'app.db'}"
    chroma_dir: str = str(DATA_DIR / "chroma")
    upload_dir: str = str(DATA_DIR / "uploads")

    # --- Document ingestion (FR02 / FR08) ---
    max_upload_size_mb: int = 20
    allowed_upload_types: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]

    # --- Chunking (T06) ---
    chunk_size_tokens: int = 400
    chunk_overlap_tokens: int = 50

    # --- Embeddings (independent of the answer-generation LLM) ---
    embedding_provider: Literal["minilm", "sentence_transformers", "ollama"] = "minilm"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_query_prefix: str = ""
    embedding_document_prefix: str = ""
    embedding_device: str = "cpu"
    embedding_cache_dir: str = str(DATA_DIR / "models")
    embedding_timeout_seconds: float = 120.0

    # --- Query rewriting (T14/T16/T18); independent provider ---
    query_rewrite_provider: Literal["inherit", "ollama", "openai", "gemini", "mock"] = "inherit"
    query_rewrite_enabled: bool = True
    query_rewrite_mode: Literal["always", "adaptive", "off"] = "always"
    query_rewrite_model: str = ""  # blank uses LLM_MODEL
    query_rewrite_timeout_seconds: float = Field(default=15.0, gt=0)

    # --- Retrieval (T10) ---
    retrieval_top_k: int = 5

    # --- Index consistency (RBAC drift check) ---
    verify_index_on_startup: bool = True

    # --- Logging ---
    log_dir: str = str(DATA_DIR / "logs")
    log_file: str = "rag.log"
    log_level: str = "INFO"
    log_max_bytes: int = 5 * 1024 * 1024  # 5 MB per log file
    log_backup_count: int = 3

    # --- LLM (FR04, T13): "ollama" local, "openai" / "gemini" external APIs ---
    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "llama3.2"
    # Evict Ollama models (keep_alive=0) this process loaded when the app stops.
    unload_ollama_on_shutdown: bool = True
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # --- CORS (React dev servers) ---
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]


def _ensure_runtime_dirs(settings: Settings) -> None:
    """Create runtime directories (SQLite/Chroma/uploads live under data/)."""
    for path in (DATA_DIR, Path(settings.chroma_dir), Path(settings.upload_dir)):
        path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance; ensures runtime directories exist."""
    settings = Settings()
    _ensure_runtime_dirs(settings)
    return settings
