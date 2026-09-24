"""Application configuration (T01: environment configuration).

Values load from the project-root ``.env`` file when present; every field has a
sane default so the app runs out of the box for local development.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> project root is three levels up
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

# MIME types accepted for ingestion (FR02)
SUPPORTED_FILE_EXTENSIONS = (".pdf", ".docx")


# Known placeholder SECRET_KEY values: production (APP_DEBUG=false) must refuse
# to start with one of these, or anyone who reads the repo could forge tokens.
_PLACEHOLDER_SECRET_KEYS = frozenset(
    {"dev-only-change-me", "change-me-to-a-long-random-string"}
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 1. Application & auth ---
    app_name: str = "AI Employee Knowledge Assistant"
    app_version: str = "0.1.0"
    debug: bool = Field(
        default=True,
        validation_alias=AliasChoices("debug", "app_debug", "DEBUG", "APP_DEBUG"),
    )

    # --- Sessions / security (FR01) ---
    secret_key: str = "dev-only-change-me"
    access_token_expire_minutes: int = 60

    # --- 2. Storage (optional overrides; defaults live under ./data/) ---
    database_url: str = f"sqlite:///{DATA_DIR / 'app.db'}"
    chroma_dir: str = str(DATA_DIR / "chroma")
    upload_dir: str = str(DATA_DIR / "uploads")

    # --- 3. Ingestion, chunking & retrieval (FR02 / T06 / T10) ---
    max_upload_size_mb: int = 20
    allowed_upload_types: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    chunk_size_tokens: int = 400
    chunk_overlap_tokens: int = 50
    retrieval_top_k: int = 5

    # Maximum cosine *distance* (0 = identical, 2 = opposite) for a chunk to
    # count as useful evidence; everything above it falls back to the safe
    # "no information" answer. Cosine scores are NOT comparable across
    # embedding models — recalibrate this for your model and documents.
    fallback_distance_threshold: float = Field(default=0.7, ge=0.0, le=2.0)

    # --- 4. Embeddings (independent of the answer LLM; reindex after changes) ---
    embedding_provider: Literal["minilm", "sentence_transformers", "ollama"] = "minilm"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_query_prefix: str = ""
    embedding_document_prefix: str = ""
    embedding_device: str = "cpu"
    embedding_cache_dir: str = str(DATA_DIR / "models")
    embedding_timeout_seconds: float = 120.0

    # --- 5. LLM (FR04, T13): "ollama" local, "openai" / "gemini" external APIs ---
    llm_provider: str = "ollama"
    llm_model: str = "llama3.2"
    ollama_base_url: str = "http://localhost:11434"
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # --- 6. Query rewriting (T14/T16/T18); independent provider ---
    query_rewrite_provider: Literal["inherit", "ollama", "openai", "gemini", "mock"] = "inherit"
    query_rewrite_enabled: bool = True
    query_rewrite_mode: Literal["always", "adaptive", "off"] = "always"
    query_rewrite_model: str = ""  # blank uses LLM_MODEL
    query_rewrite_timeout_seconds: float = Field(default=15.0, gt=0)

    # --- 7. Logging ---
    log_dir: str = str(DATA_DIR / "logs")
    log_file: str = "rag.log"
    log_level: str = "INFO"
    log_max_bytes: int = 5 * 1024 * 1024  # 5 MB per log file
    log_backup_count: int = 3

    # --- 8. CORS (React dev servers) ---
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # --- 9. Startup behaviour ---
    # Verify vector-index permissions against SQLite at startup; blocks startup
    # on drift. Set to false only for repairs.
    verify_index_on_startup: bool = True
    # Evict Ollama models (keep_alive=0) this process loaded when the app stops.
    unload_ollama_on_shutdown: bool = True

    @model_validator(mode="after")
    def _reject_placeholder_secret_in_production(self) -> "Settings":
        """Refuse to run production (debug=false) with a placeholder SECRET_KEY.

        With the documented placeholder values, anyone who reads the repository
        could forge valid session tokens, so this is a hard startup error.
        Debug mode keeps the placeholder so the app still runs out of the box.
        """
        if not self.debug and self.secret_key.strip().lower() in _PLACEHOLDER_SECRET_KEYS:
            raise ValueError(
                "SECRET_KEY is still the documented placeholder. Set a long random "
                "string in .env (e.g. `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`) "
                "before running with APP_DEBUG=false."
            )
        return self


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
